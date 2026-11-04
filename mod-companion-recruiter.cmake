if(NOT BUILD_PLAYERBOTS)
  message(FATAL_ERROR "mod-companion-recruiter requires BUILD_PLAYERBOTS=ON")
endif()

if(TORTOISE_CURRENT_MODULE_LINKAGE STREQUAL "dynamic")
  message(FATAL_ERROR
    "mod-companion-recruiter must be built statically because PlayerBots is a static, non-PIC library")
endif()

if(TORTOISE_MODULE_CMAKE_PHASE STREQUAL "POST_TARGETS")
  if(TORTOISE_CURRENT_MODULE_LINKAGE STREQUAL "dynamic")
    set(COMPANION_RECRUITER_TARGET mod_mod_companion_recruiter)
  else()
    set(COMPANION_RECRUITER_TARGET modules)
  endif()

  if(PLAYERBOTS_IMPL STREQUAL "ac")
    # The ported module exports its include directories through the playerbots target.
    target_compile_definitions(${COMPANION_RECRUITER_TARGET} PRIVATE MANGOSBOT_ZERO ENABLE_PLAYERBOTS PLAYERBOTS_AC)
  else()
    target_include_directories(${COMPANION_RECRUITER_TARGET}
      PRIVATE
        ${CMAKE_SOURCE_DIR}/src/modules/PlayerBots
        ${CMAKE_SOURCE_DIR}/src/modules/PlayerBots/playerbot
        ${CMAKE_SOURCE_DIR}/src/modules/PlayerBots/playerbot/strategy)
    target_compile_definitions(${COMPANION_RECRUITER_TARGET} PRIVATE MANGOSBOT_ZERO ENABLE_PLAYERBOTS)
  endif()
  target_link_libraries(${COMPANION_RECRUITER_TARGET} PUBLIC playerbots)
endif()
