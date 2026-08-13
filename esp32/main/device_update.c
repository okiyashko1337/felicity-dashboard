#include "device_update.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "mbedtls/md.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nextion.h"

static const char *TAG = "device_update";
static char completed_nextion_request[40];

#define MAX_MANIFEST_RESPONSE 8192U
#define MAX_UPDATE_FILE_SIZE (4U * 1024U * 1024U)

typedef struct {
    mbedtls_md_context_t context;
    bool ready;
} sha256_context_t;

static bool sha256_begin(sha256_context_t *sha)
{
    if (!sha) return false;
    memset(sha, 0, sizeof(*sha));
    mbedtls_md_init(&sha->context);
    const mbedtls_md_info_t *info =
        mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!info || mbedtls_md_setup(&sha->context, info, 0) != 0 ||
        mbedtls_md_starts(&sha->context) != 0) {
        mbedtls_md_free(&sha->context);
        return false;
    }
    sha->ready = true;
    return true;
}

static bool sha256_update(sha256_context_t *sha, const void *data, size_t size)
{
    return sha && sha->ready && data &&
           mbedtls_md_update(&sha->context, data, size) == 0;
}

static bool sha256_finish(sha256_context_t *sha, unsigned char digest[32])
{
    if (!sha || !sha->ready || !digest) return false;
    bool ok = mbedtls_md_finish(&sha->context, digest) == 0;
    mbedtls_md_free(&sha->context);
    sha->ready = false;
    return ok;
}

typedef struct {
    char *data;
    size_t length;
    size_t capacity;
} response_buffer_t;

static esp_err_t collect_response(esp_http_client_event_t *event)
{
    response_buffer_t *buffer = event->user_data;
    if (event->event_id != HTTP_EVENT_ON_DATA || !buffer || event->data_len <= 0) {
        return ESP_OK;
    }
    size_t required = buffer->length + (size_t)event->data_len + 1;
    if (required > MAX_MANIFEST_RESPONSE) return ESP_ERR_INVALID_SIZE;
    if (required > buffer->capacity) {
        size_t capacity = required + 512;
        char *next = realloc(buffer->data, capacity);
        if (!next) return ESP_ERR_NO_MEM;
        buffer->data = next;
        buffer->capacity = capacity;
    }
    memcpy(buffer->data + buffer->length, event->data, event->data_len);
    buffer->length += (size_t)event->data_len;
    buffer->data[buffer->length] = '\0';
    return ESP_OK;
}

static void make_url(const char *base, const char *path, char *url, size_t size)
{
    if (!path || !path[0]) {
        url[0] = '\0';
    } else if (strncmp(path, "http://", 7) == 0 ||
               strncmp(path, "https://", 8) == 0) {
        snprintf(url, size, "%s", path);
    } else {
        snprintf(url, size, "%s%s%s", base, path[0] == '/' ? "" : "/", path);
    }
}

static int read_chunk(esp_http_client_handle_t client, void *buffer, size_t size)
{
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
        int result = esp_http_client_read(client, buffer, size);
        if (result != -ESP_ERR_HTTP_EAGAIN) return result;
    }
    return -1;
}

static bool sha256_matches(const unsigned char digest[32], const char *expected)
{
    if (!expected || strlen(expected) != 64) return false;
    char actual[65];
    for (size_t i = 0; i < 32; ++i) {
        snprintf(actual + i * 2, 3, "%02x", digest[i]);
    }
    return strcasecmp(actual, expected) == 0;
}

static bool send_report(const char *base, const device_update_request_t *request,
                        const char *state, unsigned progress, const char *message)
{
    char url[192];
    snprintf(url, sizeof(url), "%s/api/device/update/report", base);
    cJSON *root = cJSON_CreateObject();
    if (!root) return false;
    cJSON_AddStringToObject(root, "request_id", request->request_id);
    cJSON_AddStringToObject(root, "target",
                            request->target == DEVICE_UPDATE_ESP32 ? "esp32" : "nextion");
    cJSON_AddStringToObject(root, "state", state);
    cJSON_AddNumberToObject(root, "progress_percent", progress);
    cJSON_AddStringToObject(root, "device_version",
                            esp_app_get_description()->version);
    cJSON_AddStringToObject(root, "message", message ? message : "");
    char *body = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!body) return false;
    esp_http_client_config_t config = {
        .url = url,
        .timeout_ms = 5000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        free(body);
        return false;
    }
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, body, (int)strlen(body));
    esp_err_t result = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    free(body);
    return result == ESP_OK && status == 200;
}

static bool confirm_running_version(const char *base)
{
    char url[192];
    snprintf(url, sizeof(url), "%s/api/device/update/confirm", base);
    char body[96];
    snprintf(body, sizeof(body), "{\"device_version\":\"%s\"}",
             esp_app_get_description()->version);
    esp_http_client_config_t config = {.url = url, .timeout_ms = 5000};
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return false;
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, body, (int)strlen(body));
    esp_err_t result = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    return result == ESP_OK && status == 200;
}

bool device_update_poll(const char *base, device_update_request_t *request)
{
    if (!base || !base[0] || !request) return false;
    char url[192];
    snprintf(url, sizeof(url), "%s/api/device/update", base);
    response_buffer_t response = {0};
    esp_http_client_config_t config = {
        .url = url,
        .event_handler = collect_response,
        .user_data = &response,
        .timeout_ms = 5000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return false;
    esp_err_t result = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    if (result != ESP_OK || status != 200 || !response.data) {
        free(response.data);
        return false;
    }
    cJSON *document = cJSON_Parse(response.data);
    free(response.data);
    cJSON *active = document ? cJSON_GetObjectItemCaseSensitive(document, "request") : NULL;
    if (!cJSON_IsObject(active)) {
        cJSON_Delete(document);
        return false;
    }
    cJSON *id = cJSON_GetObjectItemCaseSensitive(active, "id");
    cJSON *target = cJSON_GetObjectItemCaseSensitive(active, "target");
    cJSON *firmware = cJSON_GetObjectItemCaseSensitive(document, "firmware");
    cJSON *metadata = cJSON_IsString(target)
                          ? cJSON_GetObjectItemCaseSensitive(firmware, target->valuestring)
                          : NULL;
    cJSON *version = cJSON_GetObjectItemCaseSensitive(metadata, "version");
    cJSON *size = cJSON_GetObjectItemCaseSensitive(metadata, "size");
    cJSON *sha = cJSON_GetObjectItemCaseSensitive(metadata, "sha256");
    cJSON *download = cJSON_GetObjectItemCaseSensitive(metadata, "download_url");
    bool valid = cJSON_IsString(id) && cJSON_IsString(target) &&
                 cJSON_IsObject(metadata) && cJSON_IsString(version) &&
                 cJSON_IsNumber(size) && size->valuedouble > 0 &&
                 size->valuedouble <= MAX_UPDATE_FILE_SIZE &&
                 size->valuedouble == (double)(size_t)size->valuedouble &&
                 cJSON_IsString(sha) && cJSON_IsString(download);
    if (valid) {
        memset(request, 0, sizeof(*request));
        snprintf(request->request_id, sizeof(request->request_id), "%s", id->valuestring);
        snprintf(request->version, sizeof(request->version), "%s", version->valuestring);
        snprintf(request->sha256, sizeof(request->sha256), "%s", sha->valuestring);
        snprintf(request->download_url, sizeof(request->download_url), "%s", download->valuestring);
        request->size = (size_t)size->valuedouble;
        request->target = strcmp(target->valuestring, "esp32") == 0
                              ? DEVICE_UPDATE_ESP32
                          : strcmp(target->valuestring, "nextion") == 0
                              ? DEVICE_UPDATE_NEXTION
                              : DEVICE_UPDATE_NONE;
        valid = request->target != DEVICE_UPDATE_NONE;
    }
    cJSON_Delete(document);
    return valid;
}

static bool apply_esp32(const char *base, const device_update_request_t *request)
{
    char url[256];
    make_url(base, request->download_url, url, sizeof(url));
    esp_http_client_config_t config = {.url = url, .timeout_ms = 10000};
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return false;
    if (esp_http_client_open(client, 0) != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }
    int64_t length = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    if (status != 200 || length <= 0 || (size_t)length != request->size) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return false;
    }
    const esp_partition_t *partition = esp_ota_get_next_update_partition(NULL);
    esp_ota_handle_t handle = 0;
    if (!partition || esp_ota_begin(partition, request->size, &handle) != ESP_OK) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return false;
    }
    sha256_context_t sha;
    uint8_t buffer[4096];
    size_t received = 0;
    bool ok = sha256_begin(&sha);
    while (received < request->size) {
        int read = read_chunk(client, buffer, sizeof(buffer));
        if (read <= 0 || esp_ota_write(handle, buffer, (size_t)read) != ESP_OK) {
            ok = false;
            break;
        }
        ok = sha256_update(&sha, buffer, (size_t)read);
        if (!ok) break;
        received += (size_t)read;
    }
    unsigned char digest[32];
    ok = sha256_finish(&sha, digest) && ok;
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    ok = ok && received == request->size && sha256_matches(digest, request->sha256);
    if (!ok) {
        esp_ota_abort(handle);
        return false;
    }
    /* esp_ota_end() consumes the handle even when image validation fails. */
    if (esp_ota_end(handle) != ESP_OK) return false;
    esp_app_desc_t installed;
    if (esp_ota_get_partition_description(partition, &installed) != ESP_OK ||
        strcmp(installed.version, request->version) != 0) {
        ESP_LOGE(TAG, "OTA version mismatch: manifest=%s image=%s",
                 request->version, installed.version);
        return false;
    }
    if (esp_ota_set_boot_partition(partition) != ESP_OK) return false;
    send_report(base, request, "restarting", 100, "ESP32 firmware verified");
    vTaskDelay(pdMS_TO_TICKS(250));
    esp_restart();
    return true;
}

static bool apply_nextion(const char *base, const device_update_request_t *request)
{
    char url[256];
    make_url(base, request->download_url, url, sizeof(url));
    esp_http_client_config_t config = {.url = url, .timeout_ms = 10000};
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return false;
    if (esp_http_client_open(client, 0) != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }
    int64_t length = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    const esp_partition_t *staging = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, 0x40, "nextion");
    size_t erase_size = (request->size + 4095U) & ~4095U;
    bool ok = status == 200 && length > 0 && (size_t)length == request->size &&
              staging && request->size <= staging->size &&
              esp_partition_erase_range(staging, 0, erase_size) == ESP_OK;
    sha256_context_t sha;
    ok = sha256_begin(&sha) && ok;
    uint8_t buffer[4096];
    size_t received = 0;
    while (ok && received < request->size) {
        size_t wanted = request->size - received;
        if (wanted > sizeof(buffer)) wanted = sizeof(buffer);
        int read = read_chunk(client, buffer, wanted);
        if (read <= 0 ||
            esp_partition_write(staging, received, buffer, (size_t)read) != ESP_OK) {
            ok = false;
            break;
        }
        ok = sha256_update(&sha, buffer, (size_t)read);
        if (!ok) break;
        received += (size_t)read;
    }
    unsigned char digest[32];
    ok = sha256_finish(&sha, digest) && ok;
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    ok = ok && received == request->size && sha256_matches(digest, request->sha256);
    if (ok) {
        send_report(base, request, "installing", 0, "Verified TFT; flashing Nextion");
        ok = nextion_upload_begin(request->size);
    }
    /* Do not perform HTTP progress callbacks between 4096-byte UART packets.
     * Nextion expects the next packet immediately after each 0x05 ACK. */
    for (size_t offset = 0; ok && offset < request->size; offset += sizeof(buffer)) {
        size_t chunk = request->size - offset;
        if (chunk > sizeof(buffer)) chunk = sizeof(buffer);
        ok = esp_partition_read(staging, offset, buffer, chunk) == ESP_OK &&
             nextion_upload_chunk(buffer, chunk);
    }
    ok = ok && nextion_upload_finish();
    return ok;
}

bool device_update_apply(const char *base, const device_update_request_t *request)
{
    if (!base || !request || request->target == DEVICE_UPDATE_NONE) return false;
    if (request->target == DEVICE_UPDATE_ESP32 &&
        strcmp(request->version, esp_app_get_description()->version) == 0) {
        return send_report(base, request, "complete", 100,
                           "ESP32 is running the requested version");
    }
    if (request->target == DEVICE_UPDATE_NEXTION &&
        strcmp(request->request_id, completed_nextion_request) == 0) {
        return send_report(base, request, "complete", 100,
                           "Nextion update complete");
    }
    send_report(base, request, "downloading", 0,
                "Downloading and verifying update");
    bool ok = request->target == DEVICE_UPDATE_ESP32
                  ? apply_esp32(base, request)
                  : apply_nextion(base, request);
    if (ok && request->target == DEVICE_UPDATE_NEXTION) {
        /* The display has already rebooted and emitted 0x88. Keep the request
         * in RAM until HA acknowledges completion so a transient report loss
         * cannot make the next poll flash the same TFT a second time. */
        snprintf(completed_nextion_request,
                 sizeof(completed_nextion_request), "%s", request->request_id);
        send_report(base, request, "complete", 100, "Nextion update complete");
    } else if (!ok) {
        send_report(base, request, "error", 0, "Update failed verification or transfer");
    }
    return ok;
}

bool device_update_running_app_pending(void)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    return running && esp_ota_get_state_partition(running, &state) == ESP_OK &&
           state == ESP_OTA_IMG_PENDING_VERIFY;
}

void device_update_confirm_running_app(void)
{
    if (device_update_running_app_pending()) {
        ESP_ERROR_CHECK(esp_ota_mark_app_valid_cancel_rollback());
        ESP_LOGI(TAG, "Confirmed OTA image %s", esp_app_get_description()->version);
    }
}

bool device_update_confirm_with_server(const char *api_base_url)
{
    return api_base_url && api_base_url[0] && confirm_running_version(api_base_url);
}
