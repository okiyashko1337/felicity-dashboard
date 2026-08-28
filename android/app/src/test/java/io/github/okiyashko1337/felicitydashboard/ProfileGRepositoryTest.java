package io.github.okiyashko1337.felicitydashboard;

import org.junit.Test;
import static org.junit.Assert.*;

public final class ProfileGRepositoryTest {
    @Test public void selectsMainRecordingByCameraName(){ProfileGClient.ProbeResult result=new ProfileGClient.ProbeResult();result.recordings.add(new ProfileGClient.Recording("sub","Balcony AI sub","source"));result.recordings.add(new ProfileGClient.Recording("main","Balcony AI","source"));assertEquals("main",ProfileGRepository.find(result,"Balcony AI").token);}
    @Test public void returnsNullForUnrecordedDoorbell(){ProfileGClient.ProbeResult result=new ProfileGClient.ProbeResult();result.recordings.add(new ProfileGClient.Recording("main","Balcony AI","source"));assertNull(ProfileGRepository.find(result,"Улица"));}
}
