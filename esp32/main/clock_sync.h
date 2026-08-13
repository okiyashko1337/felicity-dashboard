#pragma once

#include <stdbool.h>
#include <stdint.h>

bool clock_sync_parse_iso8601(const char *timestamp, int64_t *epoch_seconds);
bool clock_sync_from_iso8601_once(const char *timestamp);
