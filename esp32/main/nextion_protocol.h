#pragma once

#include <stdbool.h>
#include <stddef.h>

bool nextion_connect_model_matches(const char *response,
                                   const char *expected_model);
void nextion_format_version_label(const char *version, char *label,
                                  size_t label_size);
