/** Version labels describe the installed packages, not an environment check. */
export function versionLabel(info) {
  const value = v => typeof v === 'string' && /^\d+\.\d+\.\d+$/.test(v) ? v : '未知';
  return `如 ${value(info?.ru)} · 规范 ${value(info?.specification)} · 如书 ${value(info?.rushu)}`;
}
