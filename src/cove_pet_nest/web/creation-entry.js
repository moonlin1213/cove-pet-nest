for (const button of document.querySelectorAll('[data-copy-creation-guide]')) {
  button.addEventListener('click', async () => {
    const message = button.parentElement.querySelector('[role=status]');
    const guide = new URL('/creation/guide', location.origin).href;
    const instruction = '请阅读我本机灵宠屋的工程 agent 升级指南，带我核对原小屋、模型配置和互动来源，最后运行离线诊断。密钥由我在本机输入。指南在 ' + guide;
    try {
      await navigator.clipboard.writeText(instruction);
      message.textContent = '已复制，可以发给你的工程 agent。';
    } catch {
      message.textContent = instruction;
    }
  });
}
