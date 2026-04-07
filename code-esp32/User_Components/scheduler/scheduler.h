#pragma once
#include <stdbool.h>

#define SCHED_MAX 10

typedef struct {
    int id;
    char action[8];       // "on"/"off"
    int auto_off;         // phút, 0 nếu không dùng
    char repeat_type[16]; // "once", "daily", "weekends"
    int active;
    int time_seconds;     // thời gian trong ngày (giây)
    int last_trigger_date;
} schedule_t;

void scheduler_init(void);
void scheduler_set_list(const schedule_t *list, int count);
void scheduler_check_and_run(void);
void scheduler_set_auto_off_expire(int sec);
void scheduler_clear_auto_off(void);
int scheduler_get_auto_off_expire(void);
void scheduler_auto_off_task(void *pv);