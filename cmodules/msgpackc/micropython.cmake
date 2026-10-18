# msgpackc for ports built with CMake (esp32, rp2).
add_library(usermod_msgpackc INTERFACE)

target_sources(usermod_msgpackc INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modmsgpackc.c
)

target_include_directories(usermod_msgpackc INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(usermod INTERFACE usermod_msgpackc)
