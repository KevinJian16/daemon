use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if let Some(window) = app.get_webview_window("main") {
        // Get screen size and position window: 15% left margin, fill rest
        if let Some(monitor) = window.current_monitor().ok().flatten() {
          let screen = monitor.size();
          let scale = monitor.scale_factor();
          let sw = screen.width as f64 / scale;
          let sh = screen.height as f64 / scale;
          let menu_bar = 25.0;
          let sm_margin = (sw * 0.15) as f64;

          let _ = window.set_position(tauri::LogicalPosition::new(sm_margin, menu_bar));
          let _ = window.set_size(tauri::LogicalSize::new(sw - sm_margin, sh - menu_bar));
        }
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
