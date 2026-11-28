// ruleid: vanohub.frontend.no-direct-axios
import axios from "axios";
// ruleid: vanohub.frontend.no-direct-axios
import { isAxiosError } from "axios";
// ok: vanohub.frontend.no-direct-axios
import type { AxiosError } from "axios";
// ruleid: vanohub.frontend.no-antd-reintroduction
import { Button } from "antd";
// ok: vanohub.frontend.no-antd-reintroduction
import { apiClient } from "@/shared/api/client";

export function Demo({ html }: { html: string }) {
  return (
    <div>
      {/* ruleid: vanohub.frontend.no-dangerously-set-inner-html */}
      <span dangerouslySetInnerHTML={{ __html: html }} />
      {/* ok: vanohub.frontend.no-dangerously-set-inner-html */}
      <span dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />
    </div>
  );
}
