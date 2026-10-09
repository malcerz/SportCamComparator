cmake_minimum_required(VERSION 3.15)
project(KomparatorGpuExporter LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find FFmpeg
set(FFMPEG_ROOT_SEARCH
    "${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg"
    "D:/BikeRideHUD-main/third_party/ffmpeg-9.0.1-full_build-shared"
    "$ENV{FFMPEG_DIR}"
)

find_path(FFMPEG_INCLUDE_DIR
    NAMES libavcodec/avcodec.h
    PATHS ${FFMPEG_ROOT_SEARCH}
    PATH_SUFFIXES include
)

find_path(FFMPEG_LIB_DIR
    NAMES avcodec.lib libavcodec.dll.a
    PATHS ${FFMPEG_ROOT_SEARCH}
    PATH_SUFFIXES lib
)

find_path(FFMPEG_BIN_DIR
    NAMES avcodec-63.dll avcodec-60.dll avcodec-59.dll
    PATHS ${FFMPEG_ROOT_SEARCH}
    PATH_SUFFIXES bin
)

if(NOT FFMPEG_INCLUDE_DIR OR NOT FFMPEG_LIB_DIR)
    message(FATAL_ERROR "FFmpeg development files not found! Checked: ${FFMPEG_ROOT_SEARCH}")
endif()

message(STATUS "Found FFmpeg include: ${FFMPEG_INCLUDE_DIR}")
message(STATUS "Found FFmpeg lib: ${FFMPEG_LIB_DIR}")
if(FFMPEG_BIN_DIR)
    message(STATUS "Found FFmpeg bin: ${FFMPEG_BIN_DIR}")
endif()

set(SOURCES
    native/KomparatorGpuExporter/main.cpp
    native/KomparatorGpuExporter/Config.cpp
    native/KomparatorGpuExporter/D3D11Context.cpp
    native/KomparatorGpuExporter/DemuxerDecoder.cpp
    native/KomparatorGpuExporter/GpuCompositor.cpp
    native/KomparatorGpuExporter/TelemetryRenderer.cpp
    native/KomparatorGpuExporter/HwEncoder.cpp
    native/KomparatorGpuExporter/NvencDirectEncoder.cpp
    native/KomparatorGpuExporter/AudioMuxer.cpp
    native/KomparatorGpuExporter/ExportPreview.cpp
    native/KomparatorGpuExporter/ExportPipeline.cpp
)

set(HEADERS
    native/KomparatorGpuExporter/Config.h
    native/KomparatorGpuExporter/D3D11Context.h
    native/KomparatorGpuExporter/DemuxerDecoder.h
    native/KomparatorGpuExporter/GpuCompositor.h
    native/KomparatorGpuExporter/TelemetryRenderer.h
    native/KomparatorGpuExporter/HwEncoder.h
    native/KomparatorGpuExporter/NvencDirectEncoder.h
    native/KomparatorGpuExporter/AudioMuxer.h
    native/KomparatorGpuExporter/ExportPipeline.h
)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/bin")

add_executable(KomparatorGpuExporter ${SOURCES} ${HEADERS})
target_compile_definitions(KomparatorGpuExporter PRIVATE NOMINMAX)

target_include_directories(KomparatorGpuExporter PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/native/KomparatorGpuExporter"
    "${CMAKE_CURRENT_SOURCE_DIR}/native/third_party"
    "${CMAKE_CURRENT_SOURCE_DIR}/native/third_party/vpl"
    "${FFMPEG_INCLUDE_DIR}"
)

target_link_directories(KomparatorGpuExporter PRIVATE
    "${FFMPEG_LIB_DIR}"
)

target_link_libraries(KomparatorGpuExporter PRIVATE
    windowscodecs
    ole32
    d3d11
    dxgi
    d2d1
    dwrite
    d3dcompiler
    avcodec
    avformat
    avutil
    avfilter
)

# Copy FFmpeg runtime DLLs to bin directory
if(FFMPEG_BIN_DIR)
    add_custom_command(TARGET KomparatorGpuExporter POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${FFMPEG_BIN_DIR}"
        "${CMAKE_CURRENT_SOURCE_DIR}/bin"
        COMMENT "Copying FFmpeg DLLs to bin directory"
    )
endif()
