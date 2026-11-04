import CoreMedia
import Foundation

/// Fixed model and decoder inputs for the 0106 iOS proof of concept.
public enum DeviceCaptureContract {
    public static let modelName = "CardEventNet"
    public static let modelVersion = "CardEventNet0103M3-b3f41726c2029e6047bd9ea04ab742fc55868e815f2601410dc266a8ca736bfd"
    public static let sourcePackageSHA256 =
        "b3f41726c2029e6047bd9ea04ab742fc55868e815f2601410dc266a8ca736bfd"
    public static let checkpointSHA256 =
        "258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4"
    public static let preprocessing = "full_frame_letterbox_v1"

    public static let decoderConfiguration = CausalEventDecoder.Configuration(
        threshold: 0.4271905720,
        peakConfirmation: CMTime(seconds: 0.125, preferredTimescale: 600),
        minimumEventGap: CMTime(seconds: 0.625, preferredTimescale: 600)
    )
}
