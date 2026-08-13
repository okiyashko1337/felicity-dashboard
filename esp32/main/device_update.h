#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef enum {
    DEVICE_UPDATE_NONE = 0,
    DEVICE_UPDATE_ESP32,
    DEVICE_UPDATE_NEXTION,
} device_update_target_t;

typedef struct {
    char request_id[40];
    char version[24];
    char sha256[65];
    char download_url[160];
    size_t size;
    device_update_target_t target;
} device_update_request_t;

bool device_update_poll(const char *api_base_url, device_update_request_t *request);
bool device_update_apply(const char *api_base_url,
                         const device_update_request_t *request);
bool device_update_running_app_pending(void);
void device_update_confirm_running_app(void);
bool device_update_confirm_with_server(const char *api_base_url);
