package io.github.okiyashko1337.felicitydashboard;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import org.junit.Test;
import java.util.List;

public final class AjaxMetadataDecoderTest {
    @Test public void decodesAjaxFigureFromOnvifMetadata(){
        String payload="CgdGaWd1cmVzEkcIwJjfwcDFlgMQgJCd6RoaNggEEi4IBhACHQAAgD+6BiIKGAoKDQrXIz4VAAAAPxIKDfCnxj0VuB4FPhIENzYgJRgBGgIIAw==";
        List<AjaxMetadataDecoder.Figure> figures=AjaxMetadataDecoder.decodePayload(java.util.Base64.getDecoder().decode(payload),"2026-08-29T09:20:45.129");
        assertFalse(figures.isEmpty());
        assertEquals("2026-08-29T09:20:45.129",figures.get(0).utc);
        assertEquals(6,figures.get(0).classCode);
        assertEquals(2,figures.get(0).stateCode);
        assertEquals("76 %",figures.get(0).confidenceLabel);
        assertEquals("vehicle",figures.get(0).type());
    }

    @Test public void mapsObservedAjaxClasses(){assertEquals("person",AjaxMetadataDecoder.typeForCode(2));assertEquals("animal",AjaxMetadataDecoder.typeForCode(3));assertEquals("vehicle",AjaxMetadataDecoder.typeForCode(6));assertEquals("",AjaxMetadataDecoder.typeForCode(99));}
}
