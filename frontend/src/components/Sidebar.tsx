/** 左侧常驻导航栏：stitch _1 aside 原版移植 */
import { useEffect, useState, type ReactNode } from 'react';

export interface SideItem {
  icon: string;
  label: string;
  active?: boolean;
  onClick?: () => void;
}

export function Sidebar({ title, items, saveNote }: { title: string; items: SideItem[]; saveNote?: ReactNode }) {
  // Stitch 设计默认采用 60px 图标栏；需要文字导航时再展开。
  const [collapsed, setCollapsed] = useState(true);
  useEffect(() => {
    document.documentElement.style.setProperty('--app-sidebar-width', collapsed ? '4rem' : '16rem');
  }, [collapsed]);
  return (
    <aside className={`fixed left-0 top-16 bottom-0 ${collapsed ? 'w-16 p-2' : 'w-64 p-space-md'} bg-surface-container-lowest border-r border-surface-variant z-40 flex flex-col justify-between transition-[width,padding] duration-200`}>
      <div className="flex flex-col gap-space-sm">
        <div className="flex items-center justify-between"><div className={collapsed ? 'sr-only' : 'px-space-sm py-space-xs font-label-sm text-label-sm text-outline uppercase tracking-wider font-semibold'}>{title}</div><button className="w-8 h-8 rounded-lg text-outline hover:bg-surface-container" onClick={() => setCollapsed((v) => !v)} type="button" aria-expanded={!collapsed} aria-label={collapsed ? '展开导航' : '折叠导航'}><span className="material-symbols-outlined text-[18px]">{collapsed ? 'chevron_right' : 'chevron_left'}</span></button></div>
        <nav className="flex flex-col gap-1">
          {items.map((item) => (
            <a
              key={item.label}
              aria-current={item.active ? 'page' : undefined}
              className={
                item.active
                  ? 'flex items-center gap-space-sm px-space-sm py-space-xs transition-colors bg-primary-container text-on-primary font-title-md rounded-lg shadow-sm cursor-pointer'
                  : 'flex items-center gap-space-sm px-space-sm py-space-xs rounded-lg font-body-md text-body-md text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors cursor-pointer'
              }
              onClick={item.onClick}
              title={item.label}
            >
              <span className="material-symbols-outlined text-lg">{item.icon}</span>
              <span className={collapsed ? 'sr-only' : ''}>{item.label}</span>
            </a>
          ))}
        </nav>
      </div>
      <div className={`p-space-sm rounded-lg bg-surface-container border border-outline-variant/60 flex items-center gap-space-sm ${collapsed ? 'justify-center' : ''}`}>
        <span className="material-symbols-outlined text-primary text-lg">sync</span>
        <div className={collapsed ? 'sr-only' : 'flex flex-col'}>
          <span className="font-label-sm text-label-sm text-on-surface font-medium">研习进度已保存</span>
          {saveNote ?? <span className="font-label-sm text-label-sm text-outline">本地作答已暂存</span>}
        </div>
      </div>
    </aside>
  );
}
