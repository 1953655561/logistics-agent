import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Input,
  Modal,
  Space,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import styles from "./ImportCaseModal.module.css";

const KNOWN_DOCS = ["contract", "invoice", "packing_list", "bl", "declaration"] as const;
const DOC_LABEL: Record<string, string> = {
  contract: "合同",
  invoice: "发票",
  packing_list: "箱单",
  bl: "提单",
  declaration: "报关单",
};

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: (caseId: string) => void;
}

interface Parsed {
  docs?: Record<string, unknown>;
  error?: string;
  summary?: string;
  present?: string[];
}

function parseDocs(raw: string): Parsed {
  if (!raw.trim()) return { error: "请粘贴或上传 JSON" };
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    return { error: `JSON 解析失败：${(err as Error).message}` };
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { error: "顶层必须是对象，例如 {\"invoice\": {...}, \"declaration\": {...}}" };
  }
  const docs = data as Record<string, unknown>;
  const present = KNOWN_DOCS.filter((k) => k in docs);
  if (!present.length) {
    return { error: "至少需要 invoice 或 declaration 其中一项" };
  }
  const missing = KNOWN_DOCS.filter((k) => !(k in docs));
  let itemCount = 0;
  for (const key of ["declaration", "invoice"] as const) {
    const doc = docs[key];
    if (doc && typeof doc === "object" && !Array.isArray(doc)) {
      const items = (doc as Record<string, unknown>).items;
      if (Array.isArray(items) && items.length) {
        itemCount = items.length;
        break;
      }
    }
  }
  return {
    docs,
    present,
    summary: `识别到 ${present.length}/5 份单证${
      missing.length ? `，缺少 ${missing.join(" / ")}` : ""
    }；商品项 ${itemCount} 条`,
  };
}

export default function ImportCaseModal({ open, onClose, onImported }: Props) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [caseId, setCaseId] = useState("");
  const [text, setText] = useState("");
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (open) {
      setCaseId("");
      setText("");
      setLoadError("");
    }
  }, [open]);

  const parsed = useMemo(() => parseDocs(text), [text]);

  const loadSample = async () => {
    setLoadError("");
    try {
      const res = await api.getDocs("IMP-0019");
      setText(JSON.stringify(res.docs, null, 2));
      setCaseId("CUSTOM-001");
    } catch (err) {
      setLoadError((err as Error).message);
    }
  };

  const beforeUpload: UploadProps["beforeUpload"] = (file) => {
    if (file.size > 1_000_000) {
      setLoadError("文件超过 1MB，请精简后再传");
      return false;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setText(String(reader.result || ""));
      setLoadError("");
    };
    reader.onerror = () => setLoadError("读取文件失败");
    reader.readAsText(file, "utf-8");
    return false;
  };

  const submit = useMutation({
    mutationFn: () => {
      if (!parsed.docs) throw new Error(parsed.error || "JSON 不合法");
      return api.importCase(caseId.trim(), parsed.docs);
    },
    onSuccess: (data) => {
      message.success(`已导入并审核：${data.case_id} · ${data.verdict}`);
      queryClient.setQueryData(["case", data.case_id], data);
      queryClient.invalidateQueries({ queryKey: ["cases"] });
      onImported(data.case_id);
      onClose();
    },
    onError: (err: Error) => message.error(err.message),
  });

  const canSubmit = Boolean(parsed.docs) && !submit.isPending;

  return (
    <Modal
      title="导入单证并审核"
      open={open}
      onCancel={onClose}
      width={820}
      destroyOnClose
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={submit.isPending} disabled={!canSubmit}
                  onClick={() => submit.mutate()}>
            导入并审核
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="粘贴或上传结构化单证 JSON"
          description="顶层是五份单证：contract / invoice / packing_list / bl / declaration。可以只传其中几份用于测试缺单证场景；业务缺陷（金额、数量、要素）交给规则引擎判断。"
        />

        <div className={styles.row}>
          <Input
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            placeholder="案件编号（可留空自动生成，如 CUSTOM-001）"
            style={{ flex: 1 }}
            maxLength={40}
          />
          <Button onClick={loadSample}>载入示例（IMP-0019）</Button>
          <Upload accept=".json,application/json" showUploadList={false}
                  beforeUpload={beforeUpload}>
            <Button>选择 JSON 文件</Button>
          </Upload>
        </div>

        <Input.TextArea
          className={styles.editor}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={15}
          spellCheck={false}
          placeholder={'{\n  "contract": {...},\n  "invoice": {...},\n  "packing_list": {...},\n  "bl": {...},\n  "declaration": {...}\n}'}
        />

        {text.trim() ? (
          parsed.error ? (
            <Alert type="error" showIcon message={parsed.error} />
          ) : (
            <Space wrap>
              <Tag color="green">JSON 可解析</Tag>
              {(parsed.present ?? []).map((k) => (
                <Tag key={k}>{DOC_LABEL[k] ?? k}</Tag>
              ))}
              <Typography.Text type="secondary">{parsed.summary}</Typography.Text>
            </Space>
          )
        ) : null}

        {loadError ? <Alert type="warning" showIcon message={loadError} /> : null}

        <Typography.Text type="secondary" className={styles.hint}>
          提示：导入的原始单证只读，系统只出审核意见；同一编号重复导入会自动加后缀，避免覆盖历史记录。
        </Typography.Text>
      </Space>
    </Modal>
  );
}
