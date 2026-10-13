cmake_minimum_required(VERSION 3.5)
add_compile_options(-DconfigSUPPORT_STATIC_ALLOCATION=1)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(micros_esp8266)
