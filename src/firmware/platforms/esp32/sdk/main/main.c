#include <micros/platform.h>
#include <micros/capabilities.h>
#include <micros/controller.h>
__attribute__((used)) const unsigned micros_arena_placement_version = 1;
void app_main(void) { micros_controller_run(); }
