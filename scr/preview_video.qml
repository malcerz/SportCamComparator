import QtQuick
import QtMultimedia

Rectangle {
    id: root
    color: "black"
    property string overlayText: ""
    property bool diagnosticRed: false
    property real overlayFontScale: 1.0
    property real overlayOpacity: 1.0
    readonly property alias videoSink: video.videoSink
    readonly property rect actualVideoRect: video.contentRect

    VideoOutput {
        id: video
        objectName: "previewVideoOutput"
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectFit
    }

    Item {
        id: overlay
        objectName: "telemetryOverlay"
        z: 1
        visible: root.overlayText.trim().length > 0
        readonly property int padding: Math.max(4, Math.floor(video.contentRect.width / 150))
        x: video.contentRect.x + padding
        y: video.contentRect.y + padding
        width: telemetry.implicitWidth + 2 * padding
        height: telemetry.implicitHeight + 2 * padding

        // No MouseArea or pointer handler: the overlay never captures input.
        Text {
            id: telemetry
            objectName: "telemetryText"
            x: overlay.padding
            y: overlay.padding
            text: root.overlayText
            textFormat: Text.PlainText
            color: "white"
            style: Text.Outline
            styleColor: "black"
            font.family: "Consolas"
            font.bold: true
            font.pointSize: Math.max(6, Math.floor((video.contentRect.width / 80) * root.overlayFontScale))
            opacity: root.overlayOpacity
        }
    }
}
