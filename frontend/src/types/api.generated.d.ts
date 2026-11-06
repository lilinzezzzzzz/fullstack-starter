// 由 pnpm api:types 生成，请勿手动编辑。
export interface paths {
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 获取健康状态 */
        get: operations["get_health"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/hello": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 获取 Hello 欢迎语 */
        get: operations["get_hello"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** 客户端配置 */
        ClientSettings: {
            /**
             * 写操作重试次数
             * @constant
             */
            mutation_retry_attempts: 0;
            /** 查询缓存保留时间（秒） */
            query_cache_seconds: number;
            /** 查询重试次数 */
            query_retry_attempts: number;
            /** 查询重试间隔（秒） */
            query_retry_delay_seconds: number;
            /** 查询数据保鲜时间（秒） */
            query_stale_seconds: number;
            /** 组件挂载时重新请求 */
            refetch_on_mount: boolean;
            /** 网络重连时重新请求 */
            refetch_on_reconnect: boolean;
            /** 窗口获得焦点时重新请求 */
            refetch_on_window_focus: boolean;
            /** 请求超时时间（秒） */
            request_timeout_seconds: number;
            /** 可重试的最小 HTTP 状态码 */
            retry_min_status: number;
            /** 网络错误时重试 */
            retry_network_errors: boolean;
            /** 主题圆角半径 */
            theme_border_radius: number;
            /** 主题字体族 */
            theme_font_family: string;
            /** 主题字号 */
            theme_font_size: number;
            /** 主题主色 */
            theme_primary_color: string;
        };
        /** 错误详情条目 */
        ErrorDetail: {
            /** 字段 */
            field: string;
            /** 消息 */
            message: string;
        };
        /** 错误响应 */
        ErrorResponse: {
            /** 错误码 */
            code: string;
            /** 详情 */
            details?: components["schemas"]["ErrorDetail"][];
            /** 消息 */
            message: string;
            /** 链路标识 */
            trace_id: string;
        };
        /** 健康检查响应 */
        HealthResponse: {
            /** 数据库 */
            database: string;
            /** 状态 */
            status: string;
        };
        /** Hello 欢迎语响应 */
        HelloResponse: {
            /** 消息 */
            message: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    get_health: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description 请求成功 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            /** @description 请求无效 */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 禁止访问 */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 未找到资源 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 请求内容无法处理 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 服务器内部错误 */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 服务不可用 */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_hello: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description 请求成功 */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HelloResponse"];
                };
            };
            /** @description 请求无效 */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 禁止访问 */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 未找到资源 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 请求内容无法处理 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 服务器内部错误 */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description 服务不可用 */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
}
