import { NextRequest, NextResponse } from 'next/server';

// 后端服务基础 URL，与聊天代理保持一致
const TARGET_SERVER_BASE_URL = process.env.SERVER_BASE_URL || 'http://localhost:8001';

/**
 * Wiki 生成代理端点
 *
 * 将前端的 POST /api/wiki/generate 请求代理到后端 /wiki/generate SSE 端点。
 * 避免直接调用后端时的 CORS 问题。
 *
 * 后端返回 text/event-stream 格式的 SSE 流，此代理原样透传给前端。
 */
export async function POST(req: NextRequest) {
  try {
    const requestBody = await req.json();

    const targetUrl = `${TARGET_SERVER_BASE_URL}/wiki/generate`;

    console.log(`[Wiki Generate Proxy] Forwarding to: ${targetUrl}`);

    // 向后端发起请求
    const backendResponse = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify(requestBody),
    });

    // 如果后端返回错误，转发错误信息
    if (!backendResponse.ok) {
      const errorBody = await backendResponse.text();
      const errorHeaders = new Headers();
      backendResponse.headers.forEach((value, key) => {
        errorHeaders.set(key, value);
      });
      return new NextResponse(errorBody, {
        status: backendResponse.status,
        statusText: backendResponse.statusText,
        headers: errorHeaders,
      });
    }

    // 确保后端有响应体
    if (!backendResponse.body) {
      return new NextResponse('Backend stream body is null', { status: 500 });
    }

    // 创建 ReadableStream 将后端的 SSE 流透传给前端
    const stream = new ReadableStream({
      async start(controller) {
        const reader = backendResponse.body!.getReader();
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            controller.enqueue(value);
          }
        } catch (error) {
          console.error('[Wiki Generate Proxy] Error reading stream:', error);
          controller.error(error);
        } finally {
          controller.close();
          reader.releaseLock();
        }
      },
      cancel(reason) {
        console.log('[Wiki Generate Proxy] Client cancelled:', reason);
      },
    });

    // 设置响应头，透传 Content-Type
    const responseHeaders = new Headers();
    const contentType = backendResponse.headers.get('Content-Type');
    if (contentType) {
      responseHeaders.set('Content-Type', contentType);
    }
    responseHeaders.set('Cache-Control', 'no-cache, no-transform');

    return new NextResponse(stream, {
      status: backendResponse.status,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error('[Wiki Generate Proxy] Error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Internal Server Error';
    return new NextResponse(JSON.stringify({ error: errorMessage }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
