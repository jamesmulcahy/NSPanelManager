# Unit tests for MQTTManager. Built when NSPM_BUILD_TESTS is ON.
#
# Tests live in this directory (*_test.cpp). The older inline tests inside the library
# sources (wrapped in `#if TEST_MODE == 1`) are linked in too, so this one executable
# runs everything.

file(GLOB NSPM_TEST_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/*_test.cpp)

add_executable(nspm_mqttmanager_tests main.cpp ${NSPM_TEST_SOURCES})
target_include_directories(nspm_mqttmanager_tests PRIVATE ${CMAKE_INCLUDE_SRC_DIRECTORY} ${CMAKE_CURRENT_SOURCE_DIR})
# Recorded data some tests load at runtime (see fixtures/).
target_compile_definitions(nspm_mqttmanager_tests PRIVATE NSPM_TEST_FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures")

# Export the executable's symbols so the crash handler in main.cpp can name the functions in a backtrace.
target_link_options(nspm_mqttmanager_tests PRIVATE -rdynamic)

# nspm_core is an object library, so every one of its object files is linked in, including the
# inline tests.
target_link_libraries(nspm_mqttmanager_tests PRIVATE nspm_core)
# Its own copy rather than REUSE_FROM nspm_core: the tests are compiled with different flags.
target_precompile_headers(nspm_mqttmanager_tests PRIVATE ${NSPM_PRECOMPILED_HEADERS} <gtest/gtest.h>)

gtest_discover_tests(nspm_mqttmanager_tests DISCOVERY_TIMEOUT 60)
