import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ClipboardList, LogOut, Plus, Radar, Settings2 } from "lucide-react";
import { AuthProvider, useAuth } from "./AuthContext";
import { BrandMark, LoadingState } from "./ui";
import { CreatorDetailPage, LoginPage, NewTaskPage, TaskDetailPage, TasksPage } from "./pages";

function ProtectedLayout() {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  if (auth.loading) return <div className="full-state"><LoadingState label="正在恢复安全会话" /></div>;
  if (!auth.user) return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><BrandMark /><span><b>星采</b><small>MEDIA DESK</small></span></div>
      <nav aria-label="主导航">
        <NavLink to="/tasks" end><ClipboardList size={19} />任务中心</NavLink>
        <NavLink to="/tasks/new"><Plus size={19} />创建任务</NavLink>
      </nav>
      <div className="sidebar-note"><Radar size={17} /><div><strong>星图采集服务</strong><span>任务在服务端持续运行</span></div></div>
      <div className="account-menu">
        <div className="avatar">{auth.user.display_name.slice(0, 1)}</div>
        <div className="account-copy"><strong>{auth.user.display_name}</strong><span>@{auth.user.username}</span></div>
        <button aria-label="退出登录" title="退出登录" onClick={async () => { await auth.logout(); navigate("/login"); }}><LogOut size={17} /></button>
      </div>
    </aside>
    <main className="main-content"><Outlet /></main>
  </div>;
}

function ProductRoutes() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedLayout />}>
      <Route path="/tasks" element={<TasksPage />} />
      <Route path="/tasks/new" element={<NewTaskPage />} />
      <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
      <Route path="/tasks/:taskId/creators/:creatorId" element={<CreatorDetailPage />} />
      <Route path="/settings" element={<div className="placeholder"><Settings2 />当前里程碑不包含设置页面</div>} />
    </Route>
    <Route path="*" element={<Navigate to="/tasks" replace />} />
  </Routes>;
}

export function App() { return <AuthProvider><ProductRoutes /></AuthProvider>; }
