import { useEffect, useState } from "react";
import {
  App as AntApp,
  Button,
  Drawer,
  Input,
  Radio,
  Space,
  Typography,
} from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  open: boolean;
  caseId: string;
  verdict?: string;
  onClose: () => void;
}

export default function ApprovalDrawer({ open, caseId, verdict, onClose }: Props) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [approved, setApproved] = useState(true);
  const [comment, setComment] = useState("");

  useEffect(() => {
    if (open) {
      setApproved(true);
      setComment("");
    }
  }, [open]);

  const submit = useMutation({
    mutationFn: () => api.approve(caseId, approved, comment),
    onSuccess: (data) => {
      message.success(approved ? "已通过审批" : "已退回补正");
      queryClient.setQueryData(["case", caseId], data);
      queryClient.invalidateQueries({ queryKey: ["cases"] });
      onClose();
    },
    onError: (err: Error) => message.error(err.message),
  });

  return (
    <Drawer
      title={`人工审批 · ${caseId}`}
      width={440}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={
        <Space style={{ float: "right" }}>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            danger={!approved}
            loading={submit.isPending}
            onClick={() => {
              if (!approved && !comment.trim()) {
                message.warning("退回必须填写理由");
                return;
              }
              submit.mutate();
            }}
          >
            {approved ? "通过" : "退回"}
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={14} style={{ width: "100%" }}>
        {verdict ? (
          <Typography.Text type="secondary">当前结论：{verdict}</Typography.Text>
        ) : null}
        <Radio.Group
          value={approved}
          onChange={(e) => setApproved(e.target.value)}
          optionType="button"
          buttonStyle="solid"
          options={[
            { label: "通过", value: true },
            { label: "退回补正", value: false },
          ]}
        />
        <div>
          <Typography.Text type="secondary">
            审批意见{approved ? "（可选）" : "（退回必填）"}
          </Typography.Text>
          <Input.TextArea
            style={{ marginTop: 6 }}
            rows={4}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="例如：请补充 3C 证书与原产地证后重报"
          />
        </div>
        <Typography.Text type="secondary">
          审批门在工具层：CLI 与 Web 复用同一套状态机，审批记录会写入事件流与 trace。
        </Typography.Text>
      </Space>
    </Drawer>
  );
}
