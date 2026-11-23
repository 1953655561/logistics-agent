import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Input,
  Modal,
  Space,
  Tabs,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { UploadFile, UploadProps } from "antd";
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

const RAW_ACCEPT = ".xlsx,.xlsm,.pdf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp";

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
  const [tab, setTab] = useState<"json" | "files">("json");
  const [caseId, setCaseId] = useState("");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (open) {
      setTab("json");
      setCaseId("");
      setText("");
      setFiles([]);
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

  const ingest = useMutation({
    mutationFn: () => {
      const raw: File[] = [];
      for (const item of files) {
        if (item.originFileObj) raw.push(item.originFileObj);
      }
      if (!raw.length) throw new Error("请选择要解析的原始文件");
      return api.ingestFiles(caseId.trim(), raw);
    },
    onSuccess: (data) => {
      const meta = data.ingest;
      const text = `已解析并审核：${data.case_id} · ${meta.docs.length} 份单证 · ${data.verdict}`;
      if (meta.needs_human) {
        message.warning(`${text}（有低置信/未识别项，详情页「原始单证」可查看）`);
      } else {
        message.success(text);
      }
      queryClient.setQueryData(["case", data.case_id], data);
      queryClient.invalidateQueries({ queryKey: ["cases"] });
      queryClient.invalidateQueries({ queryKey: ["ingest", data.case_id] });
      onImported(data.case_id);
      onClose();
    },
    onError: (err: Error) => message.error(err.message),
  });

  const busy = submit.isPending || ingest.isPending;
  const canSubmit =
    tab === "json" ? Boolean(parsed.docs) && !busy : files.length > 0 && !busy;

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
          <Button
            type="primary"
            loading={busy}
            disabled={!canSubmit}
            onClick={() => (tab === "json" ? submit.mutate() : ingest.mutate())}
          >
            {tab === "json" ? "导入并审核" : "解析并审核"}
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <div className={styles.row}>
          <Input
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            placeholder="案件编号（可留空自动生成，如 CUSTOM-001）"
            style={{ flex: 1 }}
            maxLength={40}
          />
          <Button onClick={loadSample} disabled={tab !== "json"}>
            载入示例（IMP-0019）
          </Button>
          <Upload accept=".json,application/json" showUploadList={false}
                  beforeUpload={beforeUpload} disabled={tab !== "json"}>
            <Button disabled={tab !== "json"}>选择 JSON 文件</Button>
          </Upload>
        </div>

        <Tabs
          activeKey={tab}
          onChange={(key) => setTab(key as "json" | "files")}
          items={[
            {
              key: "json",
              label: "结构化 JSON",
              children: (
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  <Alert
                    type="info"
                    showIcon
                    message="粘贴或上传结构化单证 JSON"
                    description="顶层是五份单证：contract / invoice / packing_list / bl / declaration。可以只传其中几份用于测试缺单证场景；业务缺陷（金额、数量、要素）交给规则引擎判断。"
                  />
                  <Input.TextArea
                    className={styles.editor}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={13}
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
                </Space>
              ),
            },
            {
              key: "files",
              label: "原始单证（Excel / PDF / 扫描件）",
              children: (
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  <Alert
                    type="info"
                    showIcon
                    message="直接上传原始文件，系统自动识别单证类型并审核"
                    description="支持 .xlsx / .pdf / 扫描件图片；一次最多 12 个文件、单个 20MB。文字层 PDF 与 Excel 不需要 OCR；扫描件需要 OCR 依赖：本机 `pip install -r requirements-ocr.txt`，`docker compose` 默认已带 OCR（裸 `docker build` 需 `--build-arg WITH_OCR=1`）。缺依赖时会明确提示「未安装 OCR 引擎」，不会静默放行。"
                  />
                  <Upload.Dragger
                    multiple
                    accept={RAW_ACCEPT}
                    fileList={files}
                    beforeUpload={() => false}
                    onChange={({ fileList }) => setFiles(fileList)}
                  >
                    <p className="ant-upload-drag-icon">
                      <Tag color="blue">拖拽</Tag>
                    </p>
                    <p className="ant-upload-text">点击或拖拽原始单证到此处</p>
                    <p className="ant-upload-hint">
                      五单可以拆成多个文件；同一份工作簿里的多个 sheet 会自动逐张识别。
                    </p>
                  </Upload.Dragger>
                  {files.length ? (
                    <Typography.Text type="secondary">
                      已选 {files.length} 个文件；解析结果（识别到的单证、置信度、转人工项）会写入审核单详情页。
                    </Typography.Text>
                  ) : null}
                </Space>
              ),
            },
          ]}
        />

        {loadError ? <Alert type="warning" showIcon message={loadError} /> : null}

        <Typography.Text type="secondary" className={styles.hint}>
          提示：导入的原始单证只读，系统只出审核意见；同一编号重复导入会自动加后缀，避免覆盖历史记录。
        </Typography.Text>
      </Space>
    </Modal>
  );
}
