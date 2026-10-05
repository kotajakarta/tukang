import React, { useCallback, useEffect, useState } from 'react';
import { Button, Card, Input, Space, Table, Tag, Tooltip } from 'antd';
import { ReloadOutlined, AuditOutlined } from '@ant-design/icons';
import { api, AuditEntry } from '../../services/api';

const PAGE_SIZE = 100;

export const AuditView: React.FC = () => {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [username, setUsername] = useState('');
  const [action, setAction] = useState('');

  const load = useCallback(
    async (beforeId?: number) => {
      setLoading(true);
      try {
        const data = await api.getAudit({
          limit: PAGE_SIZE,
          before_id: beforeId,
          username: username || undefined,
          action: action || undefined,
        });
        setEntries((prev) => (beforeId ? [...prev, ...data] : data));
        setHasMore(data.length === PAGE_SIZE);
      } finally {
        setLoading(false);
      }
    },
    [username, action]
  );

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Card
      title={
        <span>
          <AuditOutlined className="mr-2" />
          Audit Log
        </span>
      }
      extra={
        <Space wrap>
          <Input.Search placeholder="Username" allowClear onSearch={setUsername} style={{ width: 150 }} />
          <Input.Search placeholder="Action prefix (login, POST…)" allowClear onSearch={setAction} style={{ width: 210 }} />
          <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading} />
        </Space>
      }
    >
      <Table<AuditEntry>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={entries}
        pagination={false}
        scroll={{ x: 900 }}
        columns={[
          {
            title: 'Time',
            dataIndex: 'ts',
            width: 170,
            render: (ts: number) => new Date(ts * 1000).toLocaleString(),
          },
          { title: 'User', dataIndex: 'username', width: 120, render: (u) => u || <span className="text-fg-subtle">—</span> },
          {
            title: 'Action',
            dataIndex: 'action',
            render: (a: string, row) => (
              <span className="font-mono text-xs">
                <Tag color={row.success ? 'green' : 'red'} className="mr-2">
                  {row.success ? 'OK' : 'FAIL'}
                </Tag>
                {a}
              </span>
            ),
          },
          { title: 'Server', dataIndex: 'server_id', width: 110 },
          {
            title: 'Target',
            dataIndex: 'target',
            ellipsis: { showTitle: false },
            render: (t?: string) => (
              <Tooltip title={t}>
                <span className="font-mono text-xs">{t}</span>
              </Tooltip>
            ),
          },
          { title: 'IP', dataIndex: 'ip', width: 130, render: (ip) => <span className="font-mono text-xs">{ip}</span> },
        ]}
      />
      {hasMore && entries.length > 0 && (
        <div className="text-center mt-3">
          <Button onClick={() => load(entries[entries.length - 1].id)} loading={loading}>
            Load older
          </Button>
        </div>
      )}
    </Card>
  );
};
