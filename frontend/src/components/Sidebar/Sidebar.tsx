import { LayoutDashboard, PanelLeft, PanelLeftClose, Settings } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router';
import { useAppStore } from '../../lib/store';

export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);

  const items = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <>
      {!sidebarOpen && (
        <button className="jarvis-sidebar-open" onClick={toggleSidebar} aria-label="Open navigation">
          <PanelLeft size={17} />
        </button>
      )}
      <aside className={`jarvis-sidebar ${sidebarOpen ? 'open' : ''}`} aria-label="Primary navigation">
        <div className="jarvis-brand" aria-label="OpenJarvis command center">OJ</div>
        <nav>
          {items.map((item) => {
            const active = item.path === '/' ? location.pathname === '/' || location.pathname === '/dashboard' : location.pathname === item.path;
            return (
              <button key={item.path} className={active ? 'active' : ''} onClick={() => navigate(item.path)} aria-label={item.label} title={item.label}>
                <item.icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <button className="jarvis-collapse" onClick={toggleSidebar} aria-label="Collapse navigation"><PanelLeftClose size={17} /></button>
      </aside>
    </>
  );
}
