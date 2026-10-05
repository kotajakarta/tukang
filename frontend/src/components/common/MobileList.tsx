import React, { useState } from 'react';
import { Button, Drawer, Empty, Modal, Spin } from 'antd';
import { ChevronRight } from 'lucide-react';

export type Tone = 'success' | 'danger' | 'warning' | 'neutral';

const TONE_DOT: Record<Tone, string> = {
  success: 'bg-success',
  danger: 'bg-danger',
  warning: 'bg-warning',
  neutral: 'bg-fg-subtle',
};

const TONE_TEXT: Record<Tone, string> = {
  success: 'text-success',
  danger: 'text-danger',
  warning: 'text-warning',
  neutral: 'text-fg-muted',
};

interface ResourceRowProps {
  tone: Tone;
  title: string;
  /** Small tag kept visible beside the title (the title truncates first) */
  badge?: React.ReactNode;
  subtitle?: string;
  /** Short state text shown under the title in the tone colour, e.g. "running" */
  state: string;
  onClick?: () => void;
}

/** One tappable resource (service, container) in a mobile list */
export const ResourceRow: React.FC<ResourceRowProps> = ({ tone, title, badge, subtitle, state, onClick }) => {
  const body = (
    <>
      <span aria-hidden className={`mt-1.5 h-2.5 w-2.5 rounded-full flex-shrink-0 ${TONE_DOT[tone]}`} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 min-w-0">
          <span className="truncate text-[15px] font-medium text-fg">{title}</span>
          {badge && <span className="flex-shrink-0 leading-none">{badge}</span>}
        </span>
        {subtitle && <span className="block truncate text-xs text-fg-muted mt-0.5">{subtitle}</span>}
        <span className={`block text-xs mt-1 font-medium ${TONE_TEXT[tone]}`}>{state}</span>
      </span>
      {onClick && <ChevronRight size={18} className="text-fg-subtle flex-shrink-0 self-center" aria-hidden />}
    </>
  );
  const cls = 'flex w-full items-start gap-3 px-4 py-3 text-left font-[inherit]';
  return onClick ? (
    <button type="button" onClick={onClick} className={`focus-ring ${cls} bg-transparent cursor-pointer active:bg-surface-2`}>
      {body}
    </button>
  ) : (
    <div className={cls}>{body}</div>
  );
};

interface ResourceListProps<T> {
  items: T[];
  loading: boolean;
  rowKey: (item: T) => string;
  renderRow: (item: T) => React.ReactNode;
  emptyText: string;
  /** Rows rendered before "Show more" (long unit lists stay fast on phones) */
  pageSize?: number;
}

export function ResourceList<T>({ items, loading, rowKey, renderRow, emptyText, pageSize = 40 }: ResourceListProps<T>) {
  const [limit, setLimit] = useState(pageSize);

  if (loading && items.length === 0) {
    return (
      <div className="flex justify-center py-12">
        <Spin />
      </div>
    );
  }
  if (items.length === 0) return <Empty className="py-10" description={emptyText} image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  return (
    <div className="-mx-3 sm:mx-0 sm:rounded-lg border-y sm:border border-line bg-surface">
      <ul className="list-none m-0 p-0 divide-y divide-line-muted">
        {items.slice(0, limit).map((item) => (
          <li key={rowKey(item)}>{renderRow(item)}</li>
        ))}
      </ul>
      {items.length > limit && (
        <div className="border-t border-line-muted p-3">
          <Button block onClick={() => setLimit((l) => l + pageSize)}>
            Show more ({items.length - limit} left)
          </Button>
        </div>
      )}
    </div>
  );
}

export interface SheetAction {
  key: string;
  label: string;
  icon: React.ReactNode;
  onClick: () => void | Promise<void>;
  danger?: boolean;
  /** Ask before running; the dialog's OK button repeats the action label */
  confirm?: { title: string; content?: string };
}

interface ActionSheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  badge?: React.ReactNode;
  subtitle?: string;
  tone: Tone;
  state: string;
  /** Extra facts shown above the actions */
  details?: { label: string; value: React.ReactNode }[];
  actions: SheetAction[];
}

/** Bottom sheet with a resource's details and large, confirmable actions */
export const ActionSheet: React.FC<ActionSheetProps> = ({ open, onClose, title, badge, subtitle, tone, state, details, actions }) => {
  const run = (a: SheetAction) => {
    const go = () => {
      onClose();
      return a.onClick();
    };
    if (!a.confirm) return void go();
    Modal.confirm({
      title: a.confirm.title,
      content: a.confirm.content,
      okText: a.label,
      okButtonProps: { danger: a.danger },
      centered: true,
      onOk: go,
    });
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="bottom"
      height="auto"
      rootClassName="bottom-sheet"
      closable={false}
      title={null}
      styles={{ content: { maxHeight: '85vh' } }}
    >
      <div className="flex justify-center pt-2 pb-1" aria-hidden>
        <span className="h-1 w-9 rounded-full bg-line" />
      </div>
      <div className="px-4 pt-2 pb-3 border-b border-line-muted">
        <div className="flex items-center gap-2">
          <span aria-hidden className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${TONE_DOT[tone]}`} />
          <h2 className="m-0 text-base font-semibold text-fg break-all">{title}</h2>
          {badge && <span className="flex-shrink-0 leading-none">{badge}</span>}
        </div>
        {subtitle && <p className="m-0 mt-1 text-sm text-fg-muted">{subtitle}</p>}
        <p className={`m-0 mt-1 text-sm font-medium ${TONE_TEXT[tone]}`}>{state}</p>
        {details && details.length > 0 && (
          <dl className="m-0 mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            {details.map((d) => (
              <React.Fragment key={d.label}>
                <dt className="text-fg-subtle">{d.label}</dt>
                <dd className="m-0 text-fg break-all">{d.value}</dd>
              </React.Fragment>
            ))}
          </dl>
        )}
      </div>
      {actions.length > 0 && (
        <ul className="list-none m-0 p-0 py-1">
          {actions.map((a) => (
            <li key={a.key}>
              <button
                type="button"
                onClick={() => run(a)}
                className={`focus-ring flex w-full items-center gap-3 min-h-[52px] px-4 bg-transparent text-left text-[15px] font-[inherit] cursor-pointer active:bg-surface-2 ${
                  a.danger ? 'text-danger' : 'text-fg'
                }`}
              >
                <span className={`inline-flex ${a.danger ? '' : 'text-fg-muted'}`}>{a.icon}</span>
                {a.label}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="px-4 pb-4 pt-1">
        <Button block size="large" onClick={onClose}>
          Close
        </Button>
      </div>
    </Drawer>
  );
};
