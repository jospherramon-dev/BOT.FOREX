/**
 * Conexión WebSocket a /ws/live con reconexión automática.
 *
 * Uso:
 *   const disconnect = connectLive(token, (event) => { ... });
 *   // event = {type, ts, payload} — mismos eventos del EventBus del backend.
 */

export function connectLive(token, onEvent, onStatus = () => {}) {
  let socket = null;
  let closedByUser = false;
  let retryMs = 1000;

  const connect = () => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(
      `${proto}://${window.location.host}/ws/live?token=${encodeURIComponent(token)}`,
    );

    socket.onopen = () => {
      retryMs = 1000; // resetea el backoff tras conectar
      onStatus(true);
    };

    socket.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data));
      } catch {
        /* mensaje no-JSON: se ignora */
      }
    };

    socket.onclose = (ev) => {
      onStatus(false);
      // 4401 = token inválido: no tiene sentido reintentar.
      if (closedByUser || ev.code === 4401) return;
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 10_000); // backoff exponencial ≤10s
    };

    socket.onerror = () => socket?.close();
  };

  connect();
  return () => {
    closedByUser = true;
    socket?.close();
  };
}
