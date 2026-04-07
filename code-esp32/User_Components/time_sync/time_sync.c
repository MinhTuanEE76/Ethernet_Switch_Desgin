#include "time_sync.h"
#include "esp_timer.h"
#include "esp_log.h"

static int server_seconds_base = 0;
static int64_t esp_time_base_us = 0;
static bool synced = false;

void time_sync_set_server_seconds(int seconds) {
    server_seconds_base = seconds % 86400;
    esp_time_base_us = esp_timer_get_time();
    synced = true;
    ESP_LOGI("TIME_SYNC", "Time synced: server_seconds=%d", server_seconds_base);
}

int time_sync_now_seconds(void) {
    if (!synced) return -1;
    int64_t now_us = esp_timer_get_time();
    int64_t elapsed_s = (now_us - esp_time_base_us) / 1000000LL;
    int now = (server_seconds_base + elapsed_s) % 86400;
    if (now < 0) now += 86400;
    return now;
}

int time_sync_get_server_seconds(void) {
    return synced ? server_seconds_base : -1;
}