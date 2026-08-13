#pragma once

#include <stdbool.h>

bool nextion_connect_model_matches(const char *response,
                                   const char *expected_model);
