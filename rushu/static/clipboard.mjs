/** Called only by an explicit copy-button click. Never reads the clipboard. */
export async function copyInput(text,clipboard=globalThis.navigator?.clipboard) {
  if(typeof text!=='string')throw new TypeError('复制内容必须是原始文字。');
  if(!clipboard?.writeText)throw new Error('浏览器不支持复制，请选中输入内容后手动复制。');
  try { await clipboard.writeText(text); }
  catch { throw new Error('复制未成功，请允许浏览器复制，或选中输入内容后手动复制。'); }
}
