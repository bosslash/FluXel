//! Custom non-working day management for the Gantt timeline.

use super::*;

impl FluxelApp {
    pub(super) fn open_gantt_holiday_manager(&mut self) {
        self.gantt_holiday_date = Local::now().date_naive();
        self.gantt_holiday_name.clear();
        self.gantt_holiday_delete_armed = None;
        self.gantt_holiday_manager_open = true;
    }

    pub(super) fn gantt_holiday_manager_window(&mut self, ctx: &egui::Context) {
        if !self.gantt_holiday_manager_open {
            return;
        }
        let mut open = true;
        let mut save = false;
        let mut delete = None;
        let holidays = self.gantt_holidays.clone();

        egui::Window::new("Gantt 休暇日")
            .open(&mut open)
            .anchor(Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .resizable(true)
            .default_width(480.0)
            .show(ctx, |ui| {
                ui.label(
                    RichText::new("会社休日など、タイムライン上で非稼働日として表示します。")
                        .small()
                        .color(theme::MUTED),
                );
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    ui.label("日付");
                    date_editor(ui, &mut self.gantt_holiday_date);
                });
                ui.horizontal(|ui| {
                    ui.label("名称");
                    ui.add_sized(
                        [260.0, 30.0],
                        egui::TextEdit::singleline(&mut self.gantt_holiday_name)
                            .hint_text("例: 夏季休暇"),
                    );
                    if ui.button("追加・更新").clicked() {
                        save = true;
                    }
                });
                ui.separator();
                if holidays.is_empty() {
                    ui.label(RichText::new("登録済みの休暇日はありません").color(theme::MUTED));
                } else {
                    ScrollArea::vertical().max_height(280.0).show(ui, |ui| {
                        for holiday in holidays {
                            ui.horizontal(|ui| {
                                ui.label(holiday.date.format("%Y/%m/%d").to_string());
                                ui.label(if holiday.name.is_empty() {
                                    "休暇日"
                                } else {
                                    holiday.name.as_str()
                                });
                                ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                                    if self.gantt_holiday_delete_armed == Some(holiday.date) {
                                        if ui
                                            .button(RichText::new("削除を確定").color(theme::RED))
                                            .clicked()
                                        {
                                            delete = Some(holiday.date);
                                        }
                                        if ui.button("戻る").clicked() {
                                            self.gantt_holiday_delete_armed = None;
                                        }
                                    } else if ui.button("削除").clicked() {
                                        self.gantt_holiday_delete_armed = Some(holiday.date);
                                    }
                                });
                            });
                        }
                    });
                }
            });

        if save {
            let holiday = GanttHoliday {
                date: self.gantt_holiday_date,
                name: self.gantt_holiday_name.trim().to_owned(),
            };
            match self.storage.save_gantt_holiday(&holiday) {
                Ok(()) => {
                    self.gantt_holiday_name.clear();
                    self.refresh_gantt();
                    self.set_message("休暇日を保存しました");
                }
                Err(error) => self.set_error(error),
            }
        } else if let Some(date) = delete {
            match self.storage.delete_gantt_holiday(date) {
                Ok(()) => {
                    self.gantt_holiday_delete_armed = None;
                    self.refresh_gantt();
                    self.set_message("休暇日を削除しました");
                }
                Err(error) => self.set_error(error),
            }
        }
        if !open {
            self.gantt_holiday_manager_open = false;
            self.gantt_holiday_delete_armed = None;
        }
    }
}
