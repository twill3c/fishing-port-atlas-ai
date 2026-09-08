"use client";

import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import {
  PORT_CLASS_LABEL,
  PORT_CLASS_ORDER,
  toGeoJSON,
  type PortMin,
} from "@/lib/ports";

const SOURCE_ID = "ports";
const LAYER_ID = "port-points";
const HALO_ID = "port-halo";

const GSI_PALE = "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png";
const GSI_STD = "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png";

export type BaseMapId = "pale" | "std";

interface Props {
  ports: readonly PortMin[];
  selectedPortNo: string | null;
  onSelect: (portNo: string) => void;
  baseMap: BaseMapId;
  showPoints: boolean;
}

interface HoverInfo {
  x: number;
  y: number;
  name: string;
  prefecture: string;
  municipality: string;
  portClass: string;
}

export function FishingPortMap({
  ports,
  selectedPortNo,
  onSelect,
  baseMap,
  showPoints,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const [hover, setHover] = useState<HoverInfo | null>(null);

  useEffect(() => {
    if (!container.current || map.current) return;

    const instance = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          gsi: {
            type: "raster",
            tiles: [GSI_PALE],
            tileSize: 256,
            maxzoom: 18,
            attribution:
              '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">地理院タイル</a>',
          },
        },
        layers: [{ id: "gsi", type: "raster", source: "gsi" }],
      },
      center: [137.5, 37.0],
      zoom: 4.2,
      minZoom: 3,
      maxZoom: 17,
      attributionControl: false,
    });

    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }));

    instance.on("load", () => {
      instance.addSource(SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      // 選択中の港を外側の輪で示す。色だけに頼らず大きさでも分かるようにする。
      instance.addLayer({
        id: HALO_ID,
        type: "circle",
        source: SOURCE_ID,
        filter: ["==", ["get", "port_no"], "__none__"],
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            4,
            ["*", ["get", "radius"], 2.2],
            12,
            ["*", ["get", "radius"], 3.4],
          ],
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": "#c2410c",
          "circle-stroke-width": 2.5,
        },
      });

      instance.addLayer({
        id: LAYER_ID,
        type: "circle",
        source: SOURCE_ID,
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            4,
            ["get", "radius"],
            10,
            ["*", ["get", "radius"], 1.9],
            15,
            ["*", ["get", "radius"], 2.8],
          ],
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 0.6,
          "circle-opacity": 0.92,
        },
      });

      ready.current = true;
      // 実ブラウザ検品から地図の**描画結果**を問い合わせるための入口。
      // 「点が何個あるか」をソースの件数で数えると、描かれていなくても緑になる(HC-138)。
      (window as unknown as { __atlasMap?: maplibregl.Map }).__atlasMap = instance;
      instance.fire("atlas:ready");
    });

    instance.on("mousemove", LAYER_ID, (event) => {
      const feature = event.features?.[0];
      if (!feature) return;
      instance.getCanvas().style.cursor = "pointer";
      const props = feature.properties as Record<string, string>;
      setHover({
        x: event.point.x,
        y: event.point.y,
        name: props.name,
        prefecture: props.prefecture,
        municipality: props.municipality,
        portClass: props.port_class,
      });
    });

    instance.on("mouseleave", LAYER_ID, () => {
      instance.getCanvas().style.cursor = "";
      setHover(null);
    });

    instance.on("click", LAYER_ID, (event) => {
      const feature = event.features?.[0];
      if (!feature) return;
      onSelectRef.current((feature.properties as Record<string, string>).port_no);
    });

    // 入れ物の大きさに追随させる。
    // MapLibre は初期化時の寸法でキャンバスを作るので、レイアウトが定まる前に
    // 作られると小さいまま固定される(実測 2026-09-08: 1176×300 のまま伸びず、
    // 地図の点が入れ物の外に落ちて掴めなくなった)。Drawer の開閉でも列幅が変わる。
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(container.current);

    map.current = instance;
    return () => {
      observer.disconnect();
      instance.remove();
      map.current = null;
      ready.current = false;
    };
  }, []);

  // データ更新。style が読み終わる前に呼ばれうるので、その場合は load を待つ。
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const apply = () => {
      const source = instance.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      if (!source) return;
      source.setData(toGeoJSON(showPoints ? ports : []));
      // 検品と E2E のための目印。描いた件数を DOM から読めるようにする。
      const el = instance.getContainer();
      el.dataset.portFeatureCount = String(showPoints ? toGeoJSON(ports).features.length : 0);
    };
    if (ready.current) apply();
    else instance.once("atlas:ready", apply);
  }, [ports, showPoints]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const apply = () => {
      if (!instance.getLayer(HALO_ID)) return;
      instance.setFilter(HALO_ID, [
        "==",
        ["get", "port_no"],
        selectedPortNo ?? "__none__",
      ]);
    };
    if (ready.current) apply();
    else instance.once("atlas:ready", apply);
  }, [selectedPortNo]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const apply = () => {
      const source = instance.getSource("gsi") as maplibregl.RasterTileSource | undefined;
      if (!source) return;
      source.setTiles([baseMap === "pale" ? GSI_PALE : GSI_STD]);
    };
    if (ready.current) apply();
    else instance.once("atlas:ready", apply);
  }, [baseMap]);

  return (
    <>
      <div ref={container} className="map-root" data-testid="map-root" />
      {hover ? (
        <div
          className="map-tooltip"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
          role="status"
        >
          <strong>{hover.name}漁港</strong>
          <br />
          {PORT_CLASS_LABEL[hover.portClass as (typeof PORT_CLASS_ORDER)[number]] ??
            hover.portClass}
          <br />
          {hover.prefecture}
          {hover.municipality}
        </div>
      ) : null}
      <p className="map-attribution">
        背景: 地理院タイル / 漁港: 水産庁・国土数値情報
      </p>
    </>
  );
}
