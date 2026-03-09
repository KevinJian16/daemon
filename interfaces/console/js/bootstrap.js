(async () => {
  applyConsoleLang();
  const fromQuery = _readPanelFromQuery();
  const startPanel = fromQuery || _readState();
  if (fromQuery) _writeState(fromQuery);
  showPanel(startPanel);
  setInterval(refreshAll, 60000);
})();
