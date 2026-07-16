<!--
  Copyright (C) 2023 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
-->

<template>
  <div>
    <div ref="calendarContainer" class="calendar-container">
      <div v-if="!params.static" class="calendar-input" v-bind:class="{ 'calendar-input_opened': isVisible }" v-on:click="params.static ? null : (isVisible = !isVisible)">
        {{ params.range ? selectedDateRange.map(d => d.toLocaleDateString()).join(' - ') : selectedDate.toLocaleDateString() }}
      </div>
      <div v-if="isVisible" class="calendar-wrapper" v-bind:class="{ 'calendar-wrapper_static': params.static }">
        <div class="calendar-header">
          <div class="calendar-nav calendar-nav_left">
            <button class="calendar-nav-button" type="button" v-on:click="decrementYear">
              <svg viewBox="0 0 16 16" class="calendar-nav-icon" aria-hidden="true">
                <path d="M10.5 2.5L5 8l5.5 5.5M6.5 2.5L1 8l5.5 5.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
            <button class="calendar-nav-button" type="button" v-on:click="decrementMonth">
              <svg viewBox="0 0 16 16" class="calendar-nav-icon" aria-hidden="true">
                <path d="M10.5 2.5L5 8l5.5 5.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
          <div class="month-year">
            <div class="month-dropdown">
              <button class="month" type="button" v-on:click.stop="toggleMonthDropdown">
                {{ currentMonthName }}
                <svg viewBox="0 0 14 14" class="month-dropdown-icon" aria-hidden="true">
                  <path d="M3 5l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
              <div v-if="isMonthDropdownOpen" class="month-dropdown-menu">
                <button
                  v-for="monthOption in MONTHS"
                  v-bind:key="monthOption.id"
                  class="month-dropdown-item"
                  type="button"
                  v-bind:class="{ 'month-dropdown-item_active': monthOption.id === currentDate.getMonth() }"
                  v-on:click.stop="selectMonth(monthOption.id)">
                  {{ monthOption.label }}
                </button>
              </div>
            </div>
            <span class="year">{{ currentDate.getFullYear() }}</span>
          </div>
          <div class="calendar-nav calendar-nav_right">
            <button class="calendar-nav-button" type="button" v-on:click="incrementMonth">
              <svg viewBox="0 0 16 16" class="calendar-nav-icon" aria-hidden="true">
                <path d="M5.5 2.5L11 8l-5.5 5.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
            <button class="calendar-nav-button" type="button" v-on:click="incrementYear">
              <svg viewBox="0 0 16 16" class="calendar-nav-icon" aria-hidden="true">
                <path d="M5.5 2.5L11 8l-5.5 5.5M9.5 2.5L15 8l-5.5 5.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
        </div>
        <div class="calendar-grid">
          <div v-for="day in WEEK_DAYS" v-bind:key="day.id + currentMonthName" class="week-day-header">
            {{ day.label }}
          </div>
          <div
            v-for="(date, index) in datesArray"
            v-bind:key="index"
            v-bind:class="{ 'other-month': !isCurrentMonth(date), 'calendar-day_selected': isHighlighted(date), 'calendar-day_shaded': isShaded(date) }"
            class="calendar-day"
            v-on:click="handleDateClick(date)">
            {{ date.getDate() }}
          </div>
        </div>
      </div>
    </div>
    <dochub-object
      v-bind:src="`${params.wrappedObjectSrc ?? '@entity/aspects/hierarchy?aspect=archtool.git.client'}?${wrappedObjectParam}`"
      v-bind:inline="true" />
  </div>
</template>

<script>
  import { MONTHS, WEEK_DAYS } from './constants';

  function createDatesArray(date) {
    const currentMonth = new Date(date);
    currentMonth.setMonth(currentMonth.getMonth() + 1, 0);
    const prevMonth = new Date(date);
    prevMonth.setMonth(prevMonth.getMonth(), 0);
    const nextMonth = new Date(date);
    nextMonth.setMonth(nextMonth.getMonth() + 2, 0);

    const numberOfDaysInCurrentMonth = currentMonth.getDate();
    const numberOfDaysInPrevMonth = prevMonth.getDate();

    currentMonth.setDate(1);
    const firstDay = currentMonth.getDay();

    const daysArray = [];

    for (let i = firstDay - 1; i > 0; i--) {
      daysArray.push(new Date(
        prevMonth.getFullYear(),
        prevMonth.getMonth(),
        numberOfDaysInPrevMonth - i,
        0, 0, 0, 0
      ));
    }

    for (let i = 0; i < numberOfDaysInCurrentMonth; i++) {
      daysArray.push(new Date(
        currentMonth.getFullYear(),
        currentMonth.getMonth(),
        i + 1,
        0, 0, 0, 0
      ));
    }

    for (let i = 0; i < 8; i++) {
      const date = new Date(nextMonth.getFullYear(), nextMonth.getMonth(), i + 1, 0, 0, 0, 0);
      if (date.getDay() === 1) {
        break;
      }
      daysArray.push(date);
    }

    return daysArray;
  }

  function createYearsArray(date){
    const year = date.getFullYear();
    const yearsArray = [];
    for (let i = year + 10; i > year - 30; i--) {
      yearsArray.push({ id: i, label: i.toString() });
    }
    return yearsArray;
  }

  export default {
    name: 'DatePicker',
    props: {
      params: {
        type: Object,
        default: null,
        range: {
          type: Boolean,
          required: false,
          default: false
        },
        static: {
          type: Boolean,
          required: false,
          default: false
        },
        wrappedObjectSrc: {
          type: String,
          required: false,
          default: null
        }
      }
    },
    data() {
      return {
        yearsArray: [],
        datesArray: [],
        currentDate: null,
        selectedDate: null,
        selectedDateRange: [],
        isVisible: false,
        isMonthDropdownOpen: false,
        WEEK_DAYS,
        MONTHS
      };
    },
    computed: {
      currentMonthName() {
        const monthId = this.currentDate.getMonth();
        const month = MONTHS.find(m => m.id === monthId);
        return month ? month.label : '';
      },
      wrappedObjectParam() {
        if (this.params.range) {
          const fromDate = this.selectedDateRange?.[0] ?? this.selectedDate;
          const toDate = this.selectedDateRange?.[1] ?? this.selectedDate;
          return `fromDate=${this.formatDate(fromDate)}&toDate=${this.formatDate(toDate)}`;
        } else {
          return `date=${this.selectedDate.getFullYear()}-${this.selectedDate.getMonth() + 1}-${this.selectedDate.getDate()}`;
        }
      }
    },
    watch: {
      isVisible(newValue) {
        if (this.params.static) {
          return;
        }
        if (newValue) {
          document.addEventListener('mousedown', this.handleClickOutside);
        } else {
          document.removeEventListener('mousedown', this.handleClickOutside);
        }
      },
      currentDate(newValue) {
        this.yearsArray = createYearsArray(newValue);
        this.datesArray = createDatesArray(newValue);
        this.isMonthDropdownOpen = false;
      }
    },
    created() {
      const date = new Date();
      date.setHours(0, 0, 0, 0);
      if (this.params.range) {
        this.selectedDateRange = [date, date];
      }
      this.selectedDate = date;
      this.currentDate = date;
      if (this.params.static) {
        this.isVisible = true;
      }
    },
    beforeUnmount() {
      document.removeEventListener('mousedown', this.handleClickOutside);
    },
    methods: {
      formatDate(date) {
        return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
      },
      isCurrentMonth(date) {
        return date.getMonth() === this.currentDate.getMonth() &&
          date.getFullYear() === this.currentDate.getFullYear();
      },
      handleDateClick(date) {
        if (this.params.range) {
          if (this.selectedDateRange.length < 2) {
            this.selectedDateRange = [...this.selectedDateRange, date];
          } else {
            this.selectedDateRange = [date];
          }
          this.selectedDateRange.sort((a, b) => +a - +b);
        } else {
          this.selectedDate = date;
        }
      },
      isHighlighted(date) {
        if (this.params.range) {
          return this.selectedDateRange.some(d => +d === +date);
        } else {
          return +date === +this.selectedDate;
        }
      },
      isShaded(date) {
        if (this.params.range) {
          return date > this.selectedDateRange[0] && date < this.selectedDateRange[1];
        } else {
          return false;
        }
      },
      decrementMonth() {
        const newDate = new Date(this.currentDate);
        newDate.setMonth(newDate.getMonth() - 1);
        this.currentDate = newDate;
        this.datesArray = createDatesArray(newDate);
      },
      incrementMonth() {
        const newDate = new Date(this.currentDate);
        newDate.setMonth(newDate.getMonth() + 1);
        this.currentDate = newDate;
        this.datesArray = createDatesArray(newDate);
      },
      decrementYear() {
        const newDate = new Date(this.currentDate);
        newDate.setFullYear(newDate.getFullYear() - 1);
        this.currentDate = newDate;
        this.datesArray = createDatesArray(newDate);
      },
      incrementYear() {
        const newDate = new Date(this.currentDate);
        newDate.setFullYear(newDate.getFullYear() + 1);
        this.currentDate = newDate;
        this.datesArray = createDatesArray(newDate);
      },
      handleClickOutside(event) {
        const container = this.$refs.calendarContainer;
        if (!container || container.contains(event.target)) {
          return;
        }
        this.isVisible = false;
        this.isMonthDropdownOpen = false;
      },
      toggleMonthDropdown() {
        this.isMonthDropdownOpen = !this.isMonthDropdownOpen;
      },
      selectMonth(monthId) {
        if (this.currentDate.getMonth() === monthId) {
          this.isMonthDropdownOpen = false;
          return;
        }
        const newDate = new Date(this.currentDate);
        newDate.setMonth(monthId);
        this.currentDate = newDate;
        this.datesArray = createDatesArray(newDate);
        this.isMonthDropdownOpen = false;
      }
    }
  };
</script>

<style scoped>
.calendar-container {
  display: flex;
  position: relative;
  max-width: 300px;
  flex-direction: column;
  gap: 8px;
}

.calendar-input {
  cursor: pointer;
  max-width: max-content;
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 8px 12px;
  background: white;
  display: flex;
  align-items: center;
}

.calendar-input:hover {
  background-color: #f0f0f0;
}

.calendar-input_opened {
  background-color: #00755D;
}

.calendar-wrapper {
  display: flex;
  width: max-content;
  position: absolute;
  top: 100%;
  flex-direction: column;
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 16px;
  background: white;
  z-index: 1;
}

.calendar-wrapper_static {
  position: static;
}

.calendar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid #eee;
}

.calendar-nav {
  display: flex;
  gap: 4px;
  align-items: center;
}

.calendar-nav-button {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 35px;
  min-width: 35px;
  border: none;
  background: transparent;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
  color: #333;
}

.calendar-nav-button:hover {
  background-color: #f0f0f0;
}

.calendar-nav-icon {
  width: 14px;
  height: 14px;
  display: block;
}

.month-year {
  display: flex;
  margin-inline: 4px;
  gap: 8px;
  font-size: 18px;
  font-weight: bold;
  align-items: center;
}

.month-dropdown {
  position: relative;
}

.month {
  border: none;
  background: transparent;
  font-size: inherit;
  font-weight: inherit;
  cursor: pointer;
  display: inline-flex;
  gap: 4px;
  align-items: center;
  padding: 2px 4px;
  border-radius: 4px;
}

.month:hover {
  background-color: #f0f0f0;
}

.month-dropdown-icon {
  width: 12px;
  height: 12px;
}

.month-dropdown-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  max-height: 240px;
  overflow-y: auto;
  z-index: 2;
}

.month-dropdown-item {
  border: none;
  background: transparent;
  padding: 6px 8px;
  text-align: left;
  cursor: pointer;
  font-size: 14px;
}

.month-dropdown-item:hover {
  background-color: #f5f5f5;
}

.month-dropdown-item_active {
  background-color: #e0f9e0;
  font-weight: bold;
}

.year {
  color: #666;
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
  margin-top: 16px;
}

.week-day-header {
  text-align: center;
  font-weight: bold;
  font-size: 12px;
  padding: 8px 4px;
  color: #666;
  text-transform: uppercase;
}

.calendar-day {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border-radius: 4px;
  font-size: 14px;
}

.calendar-day:hover {
  background-color: #e0f9e0;
}

.calendar-day_selected {
  background-color: #00755D;
  color: white;
}

.calendar-day_shaded {
  background-color: #f0f0f0;
}

.calendar-day.other-month {
  color: #ccc;
}

.calendar-day.other-month:hover {
  background-color: #f9f9f9;
}
</style>
