#pragma once

#include <stdbool.h>

typedef struct {
    char wifi_ssid[33];
    char wifi_password[65];
    char api_base_url[160];
} device_settings_t;

bool device_settings_load(device_settings_t *settings);
bool device_settings_save(const device_settings_t *settings);
bool device_settings_clear(void);
