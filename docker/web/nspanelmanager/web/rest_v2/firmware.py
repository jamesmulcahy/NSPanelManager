"""
/rest/v2/firmware: staging the panel firmware from a GitHub release (docs: FIRMWARE_GITHUB_PLAN.md, C2).

  * GET  /rest/v2/firmware[?releases=1][&release=<tag>]: what is staged, and what the release resolves to.
  * POST /rest/v2/firmware/stage {"release": "<tag>"}: stage both boards from it, all or nothing.

The release comes from the request, else from the firmware_github_release setting; the repository from
firmware_github_repo. All the fetching and checking is in web/github_firmware.py.
"""

import logging

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from web import github_firmware
from web.models import FirmwareUpload

from .global_settings import _GITHUB_TAG, get_firmware_github_source
from .schema import extend_schema

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    "bad_release": 400,
    "not_found": 404,
    "verification_failed": 422,
    "rate_limited": 429,
    "unreachable": 502,
    "download_failed": 502,
}


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.ChoiceField(choices=list(ERROR_STATUS))
    message = serializers.CharField()
    board = serializers.ChoiceField(choices=list(github_firmware.BOARDS), required=False, help_text="The board a verification failure is about.")


class ErrorSerializer(serializers.Serializer):
    error = ErrorDetailSerializer()


class BoardImageSerializer(serializers.Serializer):
    md5 = serializers.CharField()
    size = serializers.IntegerField()


class BoardImagesSerializer(serializers.Serializer):
    sonoff = BoardImageSerializer()
    waveshare_p4 = BoardImageSerializer()


class ResolvedReleaseSerializer(serializers.Serializer):
    tag = serializers.CharField()
    commit = serializers.CharField()
    built_at = serializers.CharField()
    run_url = serializers.CharField()
    html_url = serializers.CharField()
    boards = BoardImagesSerializer()


class StagedBoardSerializer(serializers.Serializer):
    md5 = serializers.CharField(allow_null=True, help_text="md5 of the staged file; null if there is none.")
    source = serializers.ChoiceField(choices=FirmwareUpload.Source.choices, allow_null=True, help_text="Where the staged file came from, if the manager recorded it.")
    tag = serializers.CharField(allow_null=True)
    commit = serializers.CharField(allow_null=True)
    staged_at = serializers.DateTimeField(allow_null=True)


class StagedSerializer(serializers.Serializer):
    sonoff = StagedBoardSerializer()
    waveshare_p4 = StagedBoardSerializer()


class UpToDateSerializer(serializers.Serializer):
    sonoff = serializers.BooleanField()
    waveshare_p4 = serializers.BooleanField()


class ReleaseListItemSerializer(serializers.Serializer):
    tag = serializers.CharField()
    commit = serializers.CharField(allow_null=True)
    built_at = serializers.CharField(allow_null=True)


class FirmwareStatusSerializer(serializers.Serializer):
    repo = serializers.CharField()
    release = serializers.CharField(help_text='The release asked about: "latest", or a tag.')
    resolved = ResolvedReleaseSerializer(allow_null=True, help_text="What the release is. null when GitHub could not be asked; see error.")
    staged = StagedSerializer()
    up_to_date = UpToDateSerializer(allow_null=True)
    releases = ReleaseListItemSerializer(many=True, required=False, help_text="The newest 20 releases, newest first. Only with ?releases=1.")
    error = ErrorDetailSerializer(allow_null=True)


class FirmwareQuerySerializer(serializers.Serializer):
    releases = serializers.CharField(required=False, help_text="Pass 1 to also list the newest 20 releases.")
    release = serializers.CharField(required=False, help_text='Resolve this tag ("latest" too) instead of the firmware_github_release setting.')


class StageRequestSerializer(serializers.Serializer):
    release = serializers.CharField(required=False, help_text='"latest" or a release tag. The firmware_github_release setting when omitted.')


class StagedChangeSerializer(serializers.Serializer):
    before_md5 = serializers.CharField(allow_null=True)
    after_md5 = serializers.CharField()
    changed = serializers.BooleanField()


class StageChangesSerializer(serializers.Serializer):
    sonoff = StagedChangeSerializer()
    waveshare_p4 = StagedChangeSerializer()


class StageResultSerializer(serializers.Serializer):
    tag = serializers.CharField()
    commit = serializers.CharField()
    boards = StageChangesSerializer()


def _error(error):
    detail = {"code": error.code, "message": error.message}
    if error.board:
        detail["board"] = error.board
    return detail


def _error_response(error):
    return Response({"error": _error(error)}, status=ERROR_STATUS.get(error.code, 502))


def _bad_release():
    return github_firmware.FirmwareError("bad_release", 'The release must be "latest" or a tag of letters, digits, "_", "." and "-".')


def _staged():
    staged = {}
    for model in github_firmware.BOARDS:
        md5 = github_firmware.file_md5(github_firmware.firmware_path(model))
        row = FirmwareUpload.objects.filter(md5=md5, model=model).order_by("-staged_at", "-id").first() if md5 else None
        staged[model] = {
            "md5": md5,
            "source": row.source if row else None,
            "tag": (row.tag or None) if row else None,
            "commit": (row.commit or None) if row else None,
            "staged_at": row.staged_at if row else None,
        }
    return staged


class FirmwareView(APIView):
    http_method_names = ["get", "head"]

    @extend_schema(
        parameters=[FirmwareQuerySerializer],
        responses={200: FirmwareStatusSerializer, 400: ErrorSerializer},
    )
    def get(self, request):
        repo, default_release = get_firmware_github_source()
        release = request.query_params.get("release", default_release)
        if not _GITHUB_TAG.fullmatch(release):
            return _error_response(_bad_release())

        body = {"repo": repo, "release": release, "resolved": None, "staged": _staged(), "up_to_date": None, "error": None}
        deadline = github_firmware.new_deadline()  # Resolving and listing share it: uwsgi kills a request after 20 s
        try:
            resolved = github_firmware.resolve_release(repo, release, deadline=deadline)
        except github_firmware.FirmwareError as error:
            body["error"] = _error(error)
        else:
            body["resolved"] = {
                "tag": resolved.tag,
                "commit": resolved.commit,
                "built_at": resolved.built_at,
                "run_url": resolved.run_url,
                "html_url": resolved.html_url,
                "boards": {model: {"md5": image.md5, "size": image.size} for model, image in resolved.images.items()},
            }
            body["up_to_date"] = {model: body["staged"][model]["md5"] == image.md5 for model, image in resolved.images.items()}

        if request.query_params.get("releases") == "1":
            try:
                body["releases"] = github_firmware.list_releases(repo, deadline=deadline)
            except github_firmware.FirmwareError as error:
                body["releases"] = []
                body["error"] = body["error"] or _error(error)
        return Response(body)


class FirmwareStageView(APIView):
    http_method_names = ["post"]

    @extend_schema(
        request=StageRequestSerializer,
        responses={200: StageResultSerializer, 400: ErrorSerializer, 404: ErrorSerializer, 422: ErrorSerializer, 429: ErrorSerializer, 502: ErrorSerializer},
    )
    def post(self, request):
        repo, default_release = get_firmware_github_source()
        body = request.data if isinstance(request.data, dict) else {}
        release = body.get("release", default_release)
        if not isinstance(release, str) or not _GITHUB_TAG.fullmatch(release):
            return _error_response(_bad_release())
        try:
            result = github_firmware.stage_release(repo, release)
        except github_firmware.FirmwareError as error:
            logger.warning("Staging firmware from %s %s failed: %s", repo, release, error.message)
            return _error_response(error)
        return Response({"tag": result["tag"], "commit": result["commit"], "boards": result["boards"]})
