mod lcu;

fn main() {
    tauri::Builder::default()
        .manage(lcu::LcuCredentialsState(std::sync::Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![lcu::apply_runes, lcu::apply_summoner_spells])
        .setup(|app| {
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                lcu::run_polling(app_handle).await;
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run Tauri desktop shell");
}
