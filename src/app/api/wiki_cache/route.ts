import { NextRequest, NextResponse } from 'next/server';

// Wiki 缓存统一入口（App Router route handler）
// 统一走 Next.js 层转发到 Python 后端，替代 next.config.ts 中的 rewrites 代理，
// 与 /api/wiki/projects 保持同一代理模式，便于统一鉴权、日志与类型校验。
const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_HOST || 'http://localhost:8001';
const CACHE_API_ENDPOINT = `${PYTHON_BACKEND_URL}/api/wiki_cache`;

export async function GET(request: NextRequest) {
  try {
    const query = request.nextUrl.searchParams.toString();
    const response = await fetch(`${CACHE_API_ENDPOINT}?${query}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    });

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      console.error(`Error from Python backend (${CACHE_API_ENDPOINT}): ${response.status} - ${JSON.stringify(data)}`);
      return NextResponse.json(data ?? { error: response.statusText }, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'An unknown error occurred';
    return NextResponse.json(
      { error: `Failed to connect to the Python backend. ${message}` },
      { status: 503 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    const response = await fetch(CACHE_API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      console.error(`Error from Python backend (${CACHE_API_ENDPOINT}): ${response.status} - ${JSON.stringify(data)}`);
      return NextResponse.json(data ?? { error: response.statusText }, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'An unknown error occurred';
    return NextResponse.json(
      { error: `Failed to connect to the Python backend. ${message}` },
      { status: 503 }
    );
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const query = request.nextUrl.searchParams.toString();
    const response = await fetch(`${CACHE_API_ENDPOINT}?${query}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      console.error(`Error from Python backend (${CACHE_API_ENDPOINT}): ${response.status} - ${JSON.stringify(data)}`);
      return NextResponse.json(data ?? { error: response.statusText }, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'An unknown error occurred';
    return NextResponse.json(
      { error: `Failed to connect to the Python backend. ${message}` },
      { status: 503 }
    );
  }
}
