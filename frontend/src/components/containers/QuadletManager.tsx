import React, { useEffect, useState } from 'react';
import {
  Table, Tag, Button, Space, Card, Modal, Input, Form,
  Select, Switch, message, Popconfirm
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  FileTextOutlined,
  AppstoreAddOutlined,
} from '@ant-design/icons';
import { QuadletUnit } from '../../types/system';
import { api } from '../../services/api';
import { useServer } from '../../context/ServerContext';
import { useCan } from '../../context/AuthContext';

const CONTAINER_TEMPLATE = `[Unit]
Description=My Quadlet Container
After=network-online.target

[Container]
Image=docker.io/library/nginx:alpine
PublishPort=8080:80
Volume=mydata.volume:/var/www/html
Environment=ENV=production

[Service]
Restart=always

[Install]
WantedBy=default.target
`;

const NETWORK_TEMPLATE = `[Network]
Subnet=10.89.0.0/24
Gateway=10.89.0.1
`;

const VOLUME_TEMPLATE = `[Volume]
Label=env=production
`;

export const QuadletManager: React.FC = () => {
  const { activeServer } = useServer();
  const can = useCan();
  const [quadlets, setQuadlets] = useState<QuadletUnit[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  // Editor Modal
  const [editorOpen, setEditorOpen] = useState<boolean>(false);
  const [editingFile, setEditingFile] = useState<string>('');
  const [editingPath, setEditingPath] = useState<string>('');
  const [content, setContent] = useState<string>('');
  const [isUser, setIsUser] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);

  // New Quadlet Wizard Modal
  const [wizardOpen, setWizardOpen] = useState<boolean>(false);
  const [form] = Form.useForm();

  const fetchQuadlets = async () => {
    if (!activeServer) return;
    try {
      setLoading(true);
      const data = await api.getQuadlets(activeServer.id);
      setQuadlets(data);
    } catch (e: any) {
      message.error('Failed to load Quadlet units');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQuadlets();
  }, [activeServer?.id]);

  const handleOpenEditor = async (q: QuadletUnit) => {
    if (!activeServer) return;
    try {
      setEditingFile(q.name);
      setEditingPath(q.path);
      setIsUser(q.is_user);
      const res = await api.getQuadletContent(activeServer.id, q.path);
      setContent(res.content || '');
      setEditorOpen(true);
    } catch (e: any) {
      message.error('Failed to read Quadlet content');
    }
  };

  const handleSaveEditor = async () => {
    if (!activeServer || !editingFile) return;
    try {
      setSaving(true);
      const res = await api.saveQuadlet(activeServer.id, editingFile, content, isUser, editingPath);
      if (res.success) {
        if (res.warning) message.warning(res.warning, 8);
        else message.success('Quadlet saved & systemd daemon-reload completed!');
        setEditorOpen(false);
        await fetchQuadlets();
      } else {
        message.error(res.message);
      }
    } catch (e: any) {
      message.error('Failed to save Quadlet');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (q: QuadletUnit) => {
    if (!activeServer) return;
    try {
      await api.deleteQuadlet(activeServer.id, q.path, q.is_user);
      message.success('Quadlet deleted');
      await fetchQuadlets();
    } catch (e: any) {
      message.error('Failed to delete Quadlet');
    }
  };

  const handleCreateFromWizard = async () => {
    try {
      const values = await form.validateFields();
      let initContent = CONTAINER_TEMPLATE;
      if (values.type === 'network') initContent = NETWORK_TEMPLATE;
      if (values.type === 'volume') initContent = VOLUME_TEMPLATE;

      const filename = `${values.name}.${values.type}`;
      if (!activeServer) return;

      const res = await api.saveQuadlet(activeServer.id, filename, initContent, values.is_user);
      if (res.success) {
        if (res.warning) message.warning(res.warning, 8);
        else message.success(`Created Quadlet: ${filename}`);
        setWizardOpen(false);
        form.resetFields();
        await fetchQuadlets();
      } else {
        message.error(res.message);
      }
    } catch (e) {}
  };

  const columns = [
    {
      title: 'Quadlet Name',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, r: QuadletUnit) => (
        <div>
          <span className="font-semibold text-fg">{name}</span>
          <div className="text-xs text-fg-muted font-mono">{r.path}</div>
        </div>
      ),
    },
    {
      title: 'Unit Type',
      dataIndex: 'unit_type',
      key: 'unit_type',
      render: (type: string) => {
        const color = type === 'container' ? 'blue' : type === 'network' ? 'green' : 'orange';
        return <Tag color={color} className="uppercase font-mono text-xs">{type}</Tag>;
      },
    },
    {
      title: 'Scope',
      dataIndex: 'is_user',
      key: 'is_user',
      render: (is_user: boolean) => (
        <Tag color={is_user ? 'cyan' : 'purple'}>
          {is_user ? 'Rootless (User)' : 'System-wide'}
        </Tag>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_: any, r: QuadletUnit) => (
        <Space direction="horizontal" size="small">
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleOpenEditor(r)}
          >
            {can('admin') ? 'Edit' : 'View'}
          </Button>
          {can('admin') && (
            <Popconfirm
              title={`Delete ${r.name}?`}
              onConfirm={() => handleDelete(r)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2 text-fg font-semibold">
          <AppstoreAddOutlined className="text-accent" />
          <span>Systemd Quadlet Files (.container, .network, .volume)</span>
        </div>
        <Space>
          {can('admin') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setWizardOpen(true)}
            >
              New Quadlet
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={fetchQuadlets} loading={loading}>
            Refresh
          </Button>
        </Space>
      </div>

      <Table
        dataSource={quadlets}
        // Reading unit files needs operator (they may contain secrets); editing needs admin
        columns={can('operator') ? columns : columns.filter((c) => c.key !== 'actions')}
        rowKey="path"
        loading={loading}
        pagination={{ pageSize: 8 }}
        size="middle"
        scroll={{ x: 650 }}
      />

      {/* Editor Modal */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <FileTextOutlined className="text-accent" />
            <span>Editing Quadlet: {editingFile}</span>
          </div>
        }
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        width={750}
        footer={[
          <Button key="cancel" onClick={() => setEditorOpen(false)}>
            Cancel
          </Button>,
          <Button key="save" type="primary" loading={saving} onClick={handleSaveEditor} disabled={!can('admin')}>
            Save & Daemon Reload
          </Button>,
        ]}
      >
        <div className="mb-2 text-xs text-fg-muted">
          Changes to this file will take immediate effect via <code className="text-warning">systemctl daemon-reload</code>.
        </div>
        <Input.TextArea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={15}
          className="font-mono text-xs bg-canvas text-fg border-line"
        />
      </Modal>

      {/* Wizard Modal */}
      <Modal
        title="Create New Systemd Quadlet"
        open={wizardOpen}
        onCancel={() => setWizardOpen(false)}
        onOk={handleCreateFromWizard}
        okText="Create File"
      >
        <Form form={form} layout="vertical" initialValues={{ type: 'container', is_user: true }}>
          <Form.Item name="name" label="Quadlet Base Name" rules={[{ required: true, message: 'Enter name' }]}>
            <Input placeholder="e.g. webapp or my-redis" />
          </Form.Item>
          <Form.Item name="type" label="Quadlet Type" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'container', label: '.container (Runs a container as systemd service)' },
                { value: 'network', label: '.network (Defines a podman network)' },
                { value: 'volume', label: '.volume (Defines a named persistent volume)' },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_user" label="Rootless Scope" valuePropName="checked">
            <Switch defaultChecked />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
