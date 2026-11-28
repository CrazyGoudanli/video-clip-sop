import React from "react";
import { Composition } from "remotion";
import { ShortVideoVertical } from "./ShortVideoVertical";
import { DEFAULT_PROPS, type PackagingProps } from "./types";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ShortVideoVertical"
      component={ShortVideoVertical}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={300}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={({ props }) => {
        const p = props as unknown as PackagingProps;
        const fps = p.fps || 30;
        const durationInFrames = Math.max(30, Math.round((p.durationSec || 10) * fps));
        return {
          fps,
          durationInFrames,
          width: 1080,
          height: 1920,
        };
      }}
    />
  );
};
