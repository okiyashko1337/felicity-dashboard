#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef struct {
    float pv_total_w;
    float pv1_w;
    float pv2_w;
    float load_total_w;
    float load_l1_w;
    float load_l2_w;
    float load_l3_w;
    float battery_soc;
    float battery_voltage_v;
    float battery_power_w;
    float grid_voltage_l1_v;
    float grid_voltage_l2_v;
    float grid_voltage_l3_v;
    float grid_power_w;
    float grid_frequency_hz;
    char timestamp[40];
} dashboard_snapshot_t;

#define DASHBOARD_CHART_MAX_SAMPLES 30
#define DASHBOARD_CHART_MAX_CHANNELS 4

typedef struct {
    size_t count;
    size_t channels;
    float samples[DASHBOARD_CHART_MAX_SAMPLES][DASHBOARD_CHART_MAX_CHANNELS];
} dashboard_chart_t;

typedef struct {
    float coverage_percent;
    int gap_count;
    int longest_gap_seconds;
    char latest_start[40];
    char latest_end[40];
    dashboard_chart_t chart;
} dashboard_gaps_t;

void dashboard_sample_snapshot(dashboard_snapshot_t *snapshot);
bool dashboard_parse_current(const char *json, dashboard_snapshot_t *snapshot);
bool dashboard_fetch_current(const char *base_url, dashboard_snapshot_t *snapshot);
void dashboard_sample_chart(const char *metric, dashboard_chart_t *chart);
bool dashboard_fetch_chart(const char *base_url, const char *metric, dashboard_chart_t *chart);
void dashboard_sample_gaps(dashboard_gaps_t *gaps);
bool dashboard_fetch_gaps(const char *base_url, dashboard_gaps_t *gaps);
