/** 信息架构：顶栏=一级模块；左侧栏=当前模块二级导航（由 URL 驱动，刷新自动恢复） */
import { useCallback, useEffect, useState } from 'react';

import { ensureIdentity, resetIdentity } from './api/client';
import { TopBar } from './components/TopBar';
import { Sidebar } from './components/Sidebar';
import { navigate, useRoute } from './lib/router';
import { DiagnosisPage } from './pages/DiagnosisPage';
import { DiagnosisReportPage } from './pages/DiagnosisReportPage';
import { OverviewPage } from './pages/OverviewPage';
import { PathDecisionPage } from './pages/PathDecisionPage';
import { PathPage } from './pages/PathPage';
import { RecordsMastery } from './pages/RecordsPage';
import { TutorWorkspacePage } from './pages/TutorWorkspacePage';
import { WorkbenchPage } from './pages/WorkbenchPage';
import { StitchMotivationPage } from './pages/StitchMotivationPage';
import {
  AdjustView, KnowledgeMapView, MistakesView, PathTasksView, RecordsHome, ReflectionView, WeakView, RagView,
} from './pages/SubViews';

interface SubItem { icon: string; label: string; to: string }
interface ModuleDef { label: string; subs: SubItem[] }

const MODULES: Record<string, ModuleDef> = {
  profile: {
    label: '学情与定位',
    subs: [
      { icon: 'home', label: '我的学情', to: '/profile' },
      { icon: 'insights', label: '诊断结论', to: '/profile/conclusion' },
      { icon: 'hub', label: '知识点全景', to: '/profile/map' },
      { icon: 'bookmark', label: '错题本', to: '/profile/mistakes' },
    ],
  },
  path: {
    label: '当前路径',
    subs: [
      { icon: 'alt_route', label: '路径决策', to: '/path/decision' },
      { icon: 'route', label: '推荐学习路径', to: '/path' },
      { icon: 'swap_horiz', label: '路径调整记录', to: '/path/adjust' },
      { icon: 'menu_book', label: '任务清单', to: '/path/tasks' },
    ],
  },
  today: {
    label: '今日任务',
    subs: [
      { icon: 'menu_book', label: '任务清单', to: '/today' },
      { icon: 'smart_toy', label: '启发辅导工作台', to: '/today/tutor' },
      { icon: 'neurology', label: '概念讲解', to: '/today/rag' },
      { icon: 'edit_note', label: '答题工作区', to: '/today/workspace' },
      { icon: 'bookmark', label: '错题本', to: '/today/mistakes' },
    ],
  },
  records: {
    label: '学习记录',
    subs: [
      { icon: 'emoji_events', label: '成就激励', to: '/records/motivation' },
      { icon: 'edit_square', label: '学习反思', to: '/records/reflection' },
      { icon: 'trending_up', label: '掌握度变化', to: '/records/mastery' },
      { icon: 'history_edu', label: '学习记录', to: '/records' },
    ],
  },
};

function moduleKey(path: string): string {
  const first = path.split('/').filter(Boolean)[0] ?? 'profile';
  return MODULES[first] ? first : 'profile';
}

export function App() {
  const route = useRoute();
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    ensureIdentity()
      .then(() => setReady(true))
      .catch(() => setFailed(true));
  }, []);

  const renderContent = useCallback((): React.ReactNode => {
    const first = route.parts[0] ?? 'profile';
    const second = route.parts[1];
    const full = second ? `/${first}/${second}` : `/${first}`;
    switch (full) {
      case '/today/tutor': return <TutorWorkspacePage />;
      case '/today/rag': return <RagView />;
      case '/path/decision': return <PathDecisionPage />;
      case '/profile/conclusion': return <DiagnosisReportPage />;
      case '/profile/map': return <KnowledgeMapView />;
      case '/profile/mistakes': return <MistakesView />;
      case '/profile/diagnosis': return <DiagnosisPage />;
      case '/profile/weak': return <WeakView />;
      case '/path': return <PathPage />;
      case '/path/adjust': return <AdjustView />;
      case '/path/tasks': return <PathTasksView />;
      case '/today': return <WorkbenchPage />;
      case '/today/workspace': return <WorkbenchPage />;
      case '/today/mistakes': return <MistakesView />;
      case '/records/mastery': return <RecordsMastery />;
      case '/records/reflection': return <ReflectionView />;
      case '/records/motivation': return <StitchMotivationPage />;
      case '/records': return <RecordsHome />;
      default: return <OverviewPage />;
    }
  }, [route.parts]);

  if (failed) {
    return (
      <main className="min-h-screen bg-surface flex items-center justify-center p-6">
        <div className="rounded-xl bg-surface-container-lowest border border-outline-border p-space-lg max-w-md text-center shadow-sm">
          <div className="w-12 h-12 mx-auto rounded-full bg-error-container text-on-error-container flex items-center justify-center mb-space-sm">
            <span className="material-symbols-outlined">cloud_off</span>
          </div>
          <h2 className="font-title-lg text-title-lg text-on-surface font-semibold mb-1">无法连接后端</h2>
          <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
            请先启动 backend：<code className="font-mono text-xs">cd backend && uv run uvicorn app.main:app --port 8000</code>
          </p>
          <button className="px-space-md py-space-xs rounded-lg bg-primary text-on-primary font-title-md text-title-md" onClick={() => { resetIdentity(); window.location.reload(); }} type="button">
            重试
          </button>
        </div>
      </main>
    );
  }
  if (!ready) {
    return (
      <main className="min-h-screen bg-surface flex items-center justify-center">
        <div className="text-outline font-body-md">正在建立演示身份…</div>
      </main>
    );
  }

  const key = moduleKey(route.path);
  const module = MODULES[key];
  const full = '/' + route.parts.filter(Boolean).join('/');

  return (
    <>
      <TopBar />
      {(
        <Sidebar
          title={module.label}
          items={module.subs.map((s) => ({
            icon: s.icon,
            label: s.label,
            active: full === s.to || (s.to === `/${key}` && route.parts.length <= 1),
            onClick: () => navigate(s.to),
          }))}
          saveNote={key === 'profile' ? <span className="font-label-sm text-label-sm text-outline">刚刚自动同步</span> : undefined}
        />
      )}
      <div className="app-shell-content">{renderContent()}</div>
    </>
  );
}
