cmake_minimum_required(VERSION 3.20)
project(peek_audio LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_executable(peek-audio src/main.cpp)
target_compile_definitions(peek-audio PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(peek-audio PRIVATE ole32 mmdevapi)

if(MINGW)
  # wmain como ponto de entrada; sem DLLs do MinGW para levar junto.
  target_link_options(peek-audio PRIVATE -municode -static)
elseif(MSVC)
  set_property(TARGET peek-audio PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")
endif()

# O Peek procura o helper em host/bin (e o PyInstaller o embute de lá).
set_target_properties(peek-audio PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../host/bin"
  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/../host/bin")
