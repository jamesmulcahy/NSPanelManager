cmake_minimum_required(VERSION 3.15)
project(nspm_mqttmanager)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 23)
# Build the unit tests (tests/) and compile the inline TEST_MODE tests into the libraries.
# Run them with ./run_tests.sh, or `ctest` in the build directory.
option(NSPM_BUILD_TESTS "Build the MQTTManager unit tests" OFF)
set(CMAKE_INCLUDE_SRC_DIRECTORY /MQTTManager/include)
set(PROTOBUF_SRC_DIRECTORY /MQTTManager/include/protobuf)

add_compile_options(-rdynamic -g)
add_compile_definitions(SPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_TRACE BOOST_STACKTRACE_USE_BACKTRACE BOOST_BIND_GLOBAL_PLACEHOLDERS BOOST_STACKTRACE_LIBCXX_RUNTIME_MAY_CAUSE_MEMORY_LEAK)
if(NSPM_BUILD_TESTS)
    add_compile_definitions(TEST_MODE=1)
else()
    add_compile_definitions(TEST_MODE=0)
endif()

# Statically link libraries
IF(DEFINED ENV{STRIP})
    MESSAGE("Will build as static binary!")
    ADD_LINK_OPTIONS(-static)
ENDIF()

# The following two lines are to check for address sanitazation.
# add_compile_options(-rdynamic -g -fsanitize=address)
# add_link_options(-fsanitize=address)

find_package(PahoMqttCpp REQUIRED)
find_package(spdlog REQUIRED)
find_package(CURL REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(ixwebsocket REQUIRED)
find_package(tz REQUIRED)
find_package(date REQUIRED)
find_package(protobuf REQUIRED)
find_package(SqliteOrm REQUIRED)
find_package(stb REQUIRED)
find_package(GTest REQUIRED)
find_package(Boost REQUIRED COMPONENTS signals2 stacktrace_backtrace)
find_package(prometheus-cpp REQUIRED)

# Load CMake google test module
include(GoogleTest)

# Everything except main() is one object library, so make can compile all of it in parallel.
# (With one library per module, make would not start compiling a library until every library it
# links against was built, which left most of a clean build running on a single core.) It is an
# object library rather than a static one so that changing one file doesn't rewrite an archive of
# every object file before both binaries relink.
file(GLOB PROTOBUF_PB_CC_FILES "${CMAKE_INCLUDE_SRC_DIRECTORY}/protobuf/*.pb.cc")
add_library(nspm_core OBJECT
    ${PROTOBUF_PB_CC_FILES}
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/button/button.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/button/home_assistant_button.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/button/nspm_button.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/command_manager/command_manager.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/cover/cover.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/cover/home_assistant_cover.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/cover/openhab_cover.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/database_manager/database_manager.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/entity/entity.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/entity_manager/entity_manager.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/home_assistant_manager/home_assistant_manager.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/light/home_assistant_light.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/light/light.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/light/openhab_light.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/manager_clock/manager_clock.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/media_player/home_assistant_media_player.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/media_player/home_assistant_source_player.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/media_player/home_assistant_source_volume.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/media_player/media_player.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/mqtt_manager/mqtt_manager.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/mqtt_manager_config/mqtt_manager_config.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/nextion_image_server/nextion_image_server.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/nspanel/nspanel.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/openhab_manager/openhab_manager.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/room/room.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/room/room_entities_page.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/scenes/home_assistant_scene.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/scenes/nspm_scene.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/scenes/openhab_scene.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/scenes/scene.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/switch/home_assistant_switch.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/switch/openhab_switch.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/switch/switch.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/thermostat/home_assistant_thermostat.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/thermostat/openhab_thermostat.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/thermostat/thermostat.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/weather/weather.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/web_helper/WebHelper.cpp
    ${CMAKE_INCLUDE_SRC_DIRECTORY}/websocket_server/websocket_server.cpp
)
target_include_directories(nspm_core PUBLIC ${CMAKE_INCLUDE_SRC_DIRECTORY} ${PROTOBUF_SRC_DIRECTORY} ${CURL_INCLUDE_DIR})
target_link_libraries(nspm_core PUBLIC
    protobuf::protobuf PahoMqttCpp::paho-mqttpp3-static ixwebsocket::ixwebsocket ${CURL_LIBRARIES}
    spdlog::spdlog nlohmann_json::nlohmann_json sqlite_orm::sqlite_orm tz::tz date::date stb::stb
    Boost::boost Boost::stacktrace_backtrace dl gtest::gtest
)

# Headers that most files include, parsed once per target instead of once per file. Each
# library header costs 1-5 s to parse, and almost every file includes most of them.
# (stb is left out: nextion_image_server.cpp sets macros before including it.)
set(NSPM_PRECOMPILED_HEADERS
    <algorithm> <chrono> <functional> <memory> <mutex> <optional> <string> <thread> <vector>
    <spdlog/spdlog.h> <fmt/format.h> <nlohmann/json.hpp> <curl/curl.h> <ixwebsocket/IXWebSocket.h> <sqlite_orm/sqlite_orm.h>
    <boost/algorithm/string.hpp> <boost/bind.hpp> <boost/exception/diagnostic_information.hpp> <boost/signals2.hpp> <boost/stacktrace.hpp>
    <google/protobuf/util/message_differencer.h>
    <protobuf/protobuf_formats.pb.h> <protobuf/protobuf_general.pb.h> <protobuf/protobuf_mqttmanager.pb.h> <protobuf/protobuf_nspanel.pb.h> <protobuf/protobuf_nspanel_entity.pb.h>
)
target_precompile_headers(nspm_core PRIVATE ${NSPM_PRECOMPILED_HEADERS})

add_executable(${PROJECT_NAME} src/main.cpp)
target_link_libraries(${PROJECT_NAME} nspm_core)

if(NSPM_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
