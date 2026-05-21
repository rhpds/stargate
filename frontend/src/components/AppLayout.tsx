import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  Brand,
  Masthead,
  MastheadContent,
  MastheadMain,
  Page,
  SkipToContent,
  Toolbar,
  ToolbarContent,
  ToolbarGroup,
  ToolbarItem,
} from '@patternfly/react-core';
import { useHealth } from '../api/hooks';
import ArchitectureModal from './ArchitectureModal';

export default function AppLayout() {
  const { data: health } = useHealth();
  const navigate = useNavigate();
  const location = useLocation();
  const isAdmin = location.pathname === '/admin';
  const isLLM = location.pathname === '/llm';

  const masthead = (
    <Masthead>
      <MastheadMain>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', paddingRight: '2rem' }}>
          <Brand
            src="/redhat-logo-white.svg"
            alt="Red Hat"
            heights={{ default: '28px' }}
          />
          <span style={{ fontSize: '1.1rem', fontWeight: 700, whiteSpace: 'nowrap', color: '#FFFFFF', letterSpacing: '0.5px' }}>
            StarGate Platform
          </span>
        </div>
      </MastheadMain>
      <MastheadContent>
        <Toolbar isStatic style={{ background: 'transparent' }}>
          <ToolbarContent>
            <ToolbarGroup style={{ gap: '8px' }}>
              {(isAdmin || isLLM) && (
                <ToolbarItem>
                  <NavButton active={false} onClick={() => navigate('/')}>Dashboard</NavButton>
                </ToolbarItem>
              )}
              <ToolbarItem>
                <NavButton active={isAdmin} onClick={() => navigate(isAdmin ? '/' : '/admin')}>Scanner Admin</NavButton>
              </ToolbarItem>
              <ToolbarItem>
                <NavButton active={isLLM} onClick={() => navigate(isLLM ? '/' : '/llm')}>LLM Admin</NavButton>
              </ToolbarItem>
              <ToolbarItem>
                <ArchitectureModal renderTrigger={(onClick) => <NavButton active={false} onClick={onClick}>Architecture</NavButton>} />
              </ToolbarItem>
            </ToolbarGroup>
            <ToolbarItem align={{ default: 'alignEnd' }}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '6px',
                fontSize: '0.8rem', color: health?.status === 'ok' ? '#92D400' : '#FF6B6B',
              }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  backgroundColor: health?.status === 'ok' ? '#92D400' : '#FF6B6B',
                }} />
                {health?.status === 'ok' ? 'Connected' : 'Connecting...'}
              </span>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  );

  return (
    <Page
      masthead={masthead}
      skipToContent={<SkipToContent href="#main-content">Skip to content</SkipToContent>}
    >
      <div id="main-content">
        <Outlet />
      </div>
    </Page>
  );
}

function NavButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? 'rgba(255,255,255,0.15)' : 'transparent',
        border: '1px solid rgba(255,255,255,0.25)',
        borderRadius: '4px',
        color: '#FFFFFF',
        padding: '5px 14px',
        fontSize: '0.85rem',
        fontWeight: active ? 600 : 400,
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        fontFamily: 'Red Hat Text, sans-serif',
      }}
      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.2)'; }}
      onMouseLeave={e => { e.currentTarget.style.background = active ? 'rgba(255,255,255,0.15)' : 'transparent'; }}
    >
      {children}
    </button>
  );
}
