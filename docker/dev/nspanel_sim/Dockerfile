FROM python:3.12.5-slim-bookworm
COPY requirements.txt /sim/requirements.txt
RUN pip install --no-cache-dir -r /sim/requirements.txt
COPY nspanel_sim.py /sim/nspanel_sim.py
ENTRYPOINT ["python", "-u", "/sim/nspanel_sim.py"]
