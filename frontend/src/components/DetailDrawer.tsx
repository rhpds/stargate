import { type ReactNode, useRef, useEffect } from 'react';
import {
  Drawer,
  DrawerActions,
  DrawerCloseButton,
  DrawerContent,
  DrawerHead,
  DrawerPanelContent,
  DrawerPanelBody,
} from '@patternfly/react-core';

interface Props {
  isExpanded: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  mainContent: ReactNode;
}

export default function DetailDrawer({ isExpanded, title, onClose, children, mainContent }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isExpanded && panelRef.current) {
      panelRef.current.scrollTop = 0;
      panelRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [isExpanded, title]);

  const panel = (
    <DrawerPanelContent widths={{ default: 'width_33', lg: 'width_33' }}>
      <div ref={panelRef} style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <DrawerHead style={{ flexShrink: 0, background: 'var(--rh-color--surface)', borderBottom: '1px solid var(--rh-color--border)' }}>
          <span style={{ fontWeight: 600, fontSize: '1.1rem' }}>{title}</span>
          <DrawerActions>
            <DrawerCloseButton onClick={onClose} />
          </DrawerActions>
        </DrawerHead>
        <DrawerPanelBody style={{ flex: 1, overflowY: 'auto' }}>{children}</DrawerPanelBody>
      </div>
    </DrawerPanelContent>
  );

  return (
    <Drawer isInline isExpanded={isExpanded} position="end">
      <DrawerContent panelContent={isExpanded ? panel : undefined}>
        {mainContent}
      </DrawerContent>
    </Drawer>
  );
}
