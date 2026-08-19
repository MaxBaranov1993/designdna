// Catch-all: SPA обслуживается FastAPI с /flow/{rest} и загружается Electron
// с file:// — клиентский роутер должен совпасть с любым путём. Страница не
// пререндерится (рендерит тот же <App/>, что и корневая): index.html для
// fallback-сервинга пишется из корневого маршрута.
export const prerender = false;
