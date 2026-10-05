import React, { useEffect, useState } from 'react';
import { Button, Select } from 'antd';
import { RotateCw } from 'lucide-react';
import { api } from '../../services/api';
import { LogModal } from '../common/LogModal';

interface JournalViewerModalProps {
  open: boolean;
  serverId: string;
  unitName: string;
  onClose: () => void;
}

export const JournalViewerModal: React.FC<JournalViewerModalProps> = ({ open, serverId, unitName, onClose }) => {
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [lines, setLines] = useState<number>(100);

  const fetchLogs = async () => {
    if (!unitName) return;
    try {
      setLoading(true);
      const res = await api.getUnitLogs(serverId, unitName, lines);
      setLogs(res.logs || []);
    } catch (e) {
      setLogs(['Failed to load the journal for this unit.']);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && unitName) fetchLogs();
  }, [open, unitName, lines]);

  return (
    <LogModal
      open={open}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2 min-w-0">
          <span className="text-fg-muted font-normal">Journal</span>
          <span className="font-mono text-sm truncate">{unitName}</span>
        </span>
      }
      lines={logs}
      loading={loading}
      emptyText="No journal entries for this unit."
      toolbar={
        <>
          <Select
            value={lines}
            onChange={setLines}
            aria-label="Lines to show"
            options={[50, 100, 250, 500].map((n) => ({ value: n, label: `${n} lines` }))}
          />
          <Button icon={<RotateCw size={14} />} onClick={fetchLogs} loading={loading}>
            Refresh
          </Button>
        </>
      }
    />
  );
};
