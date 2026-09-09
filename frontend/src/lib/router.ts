/** 极简 hash 路由（零依赖） */
import { useEffect, useState } from 'react';

export type Route = { path: string; parts: string[] };

function parse(): Route {
  const raw = (window.location.hash.replace(/^#/, '') || '/').split('?')[0];
  const parts = raw.split('/').filter(Boolean);
  return { path: '/' + parts.join('/'), parts };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export function navigate(path: string): void {
  window.location.hash = path;
}
