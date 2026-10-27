// Conversa com o Python (host/gui/bridge.py) pelo QWebChannel.
// O Python manda o estado inteiro a cada mudança; daqui só saem os cliques.

export function connectBridge(onState) {
  const transport = window.qt?.webChannelTransport;
  if (!transport || !window.QWebChannel) {
    return Promise.reject(new Error("Esta página só funciona dentro da janela do Peek."));
  }
  return new Promise((resolve) => {
    new window.QWebChannel(transport, (channel) => {
      const peek = channel.objects.peek;
      peek.state_changed.connect((json) => onState(JSON.parse(json)));
      peek.ready();
      resolve(peek);
    });
  });
}
