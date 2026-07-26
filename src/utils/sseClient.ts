/**
 * SSE (Server-Sent Events) 流式客户端工具
 *
 * 因为浏览器原生 EventSource API 不支持 POST 请求，
 * 此工具使用 fetch() + ReadableStream 手动解析 SSE 事件流。
 *
 * 用法:
 *   await fetchSSEStream('/wiki/generate', { ...body }, (event) => {
 *     switch (event.event) {
 *       case 'progress': console.log(event.data.message); break;
 *       case 'structure': setStructure(event.data); break;
 *       case 'page_complete': setPageContent(event.data); break;
 *       case 'complete': done(); break;
 *       case 'error': handleError(event.data); break;
 *     }
 *   });
 */

export interface SSEEvent {
  /** 事件类型，对应后端 _sse_event() 的 event_type 参数 */
  event: string;
  /** 解析后的 JSON 数据 */
  data: Record<string, unknown>;
}

/**
 * 通过 POST 请求建立 SSE 连接，逐事件回调
 *
 * @param url     SSE 端点 URL
 * @param body    请求体（JSON 序列化）
 * @param onEvent 每个 SSE 事件触发一次
 * @param signal  可选 AbortSignal 用于取消请求
 */
export async function fetchSSEStream(
  url: string,
  body: Record<string, unknown>,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    throw new Error(
      `SSE request failed (${response.status}): ${errorText || response.statusText}`,
    );
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Response body is not readable');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // 将新收到的字节解码后追加到缓冲区
      buffer += decoder.decode(value, { stream: true });

      // SSE 格式：每个事件以 \n\n 分隔
      // event: xxx\n
      // data: {"key":"val"}\n
      // \n
      const blocks = buffer.split('\n\n');

      // 最后一个块可能不完整，保留到下一次
      buffer = blocks.pop() || '';

      for (const block of blocks) {
        if (!block.trim()) continue;

        const eventMatch = block.match(/^event: (.+)$/m);
        const dataMatch = block.match(/^data: (.+)$/m);

        if (eventMatch && dataMatch) {
          // 先解析 JSON，如果解析失败只记录警告，不中断流
          let parsedData: Record<string, unknown>;
          try {
            parsedData = JSON.parse(dataMatch[1].trim());
          } catch (parseErr) {
            console.warn('[sseClient] Failed to parse SSE data chunk:', dataMatch[1], parseErr);
            continue;
          }

          // 构造事件对象后调用回调，onEvent 中的错误会自然向上传播
          const event: SSEEvent = {
            event: eventMatch[1].trim(),
            data: parsedData,
          };
          onEvent(event);
        }
      }
    }

    // 处理缓冲区中残留的数据（连接关闭后）
    if (buffer.trim()) {
      const eventMatch = buffer.match(/^event: (.+)$/m);
      const dataMatch = buffer.match(/^data: (.+)$/m);
      if (eventMatch && dataMatch) {
        try {
          onEvent({
            event: eventMatch[1].trim(),
            data: JSON.parse(dataMatch[1].trim()),
          });
        } catch (parseErr) {
          console.warn('[sseClient] Failed to parse remaining SSE data:', parseErr);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
